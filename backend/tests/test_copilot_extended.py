"""The copilot's extended-hours reads (docs/copilot-lab.md § Extended hours). Offline: the chart feed's timesales reads and
the market calendar are stubbed."""
import json
from datetime import date, datetime

import pytest

from app.ai import copilot_extended as x, copilot_tools
from app.engine import chart_feed as feed_module
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET

MON, TUE, FRI, SAT = date(2026, 11, 2), date(2026, 11, 3), date(2026, 10, 30), date(2026, 10, 31)


def at(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET)


def rows(day, *bars):
    """Timesales rows for ``day``: (HH:MM, close, volume)."""
    return [{"timestamp": int(at(day, hm).timestamp()), "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": v}
            for hm, c, v in bars]


@pytest.fixture
def feed(monkeypatch):
    """Serves stored timesales by day and records each read; the calendar is the clock unless a test sets hours."""
    state = {"days": {}, "reads": [], "hours": {}, "fail": set()}
    x._past.clear()

    def read(path, params, ttl, keep=True):
        day = date.fromisoformat(params["start"][:10])
        state["reads"].append((params["symbol"], day, keep))
        if params["symbol"] in state["fail"]:
            raise ChartFeedError("Chart requests are cooling down to stay within the data allowance.", "rate_limited")
        return {"series": {"data": state["days"].get((params["symbol"], day), [])}}, 0.0, None
    monkeypatch.setattr(feed_module.chart_feed, "read", read)
    monkeypatch.setattr(x, "_hours", lambda day: state["hours"].get(day))
    return state


@pytest.mark.parametrize("moment,expected", [(at(TUE, "08:00"), "pre-market"), (at(TUE, "10:00"), "regular"),
                                             (at(TUE, "17:00"), "after-hours"), (at(TUE, "21:00"), "closed"),
                                             (at(TUE, "03:00"), "closed"), (at(SAT, "10:00"), "closed")])
def test_the_phase_follows_new_york_hours(feed, moment, expected):
    assert x.phase(moment) == expected


def test_pre_market_is_against_the_previous_close_with_last_evenings_after_hours(feed):
    feed["days"][("NVDA", MON)] = rows(MON, ("15:59", 200.0, 5000), ("16:30", 202.0, 1000), ("19:59", 203.0, 500))
    feed["days"][("NVDA", TUE)] = rows(TUE, ("08:00", 206.0, 2000), ("09:00", 208.0, 3000), ("09:08", 250.0, 9))
    out = x.extended(["NVDA"], at(TUE, "09:08"))
    nvda = out["symbols"]["NVDA"]
    assert out["phase"] == "pre-market" and "previous session's regular close" in out["change_against"]
    # The 09:08 minute is still forming, so it is not in.
    assert nvda["premarket"] == {"last": 208.0, "last_at": "09:00", "change_pct": 4.0, "high": 208.5, "low": 205.5,
                                 "volume": 5000, "dollar_volume": 206 * 2000 + 208 * 3000}
    assert nvda["previous_session"]["date"] == "2026-11-02" and nvda["previous_session"]["regular_close"] == 200.0
    assert nvda["previous_session"]["after_hours"]["change_pct"] == 1.5 and "high" not in nvda["previous_session"]["after_hours"]


def test_monday_pre_market_steps_over_the_weekend_and_a_holiday(feed):
    feed["hours"][FRI] = {"status": "closed"}
    thu = date(2026, 10, 29)
    feed["days"][("SPY", thu)] = rows(thu, ("15:59", 700.0, 100))
    feed["days"][("SPY", MON)] = rows(MON, ("07:00", 693.0, 100))
    out = x.extended(["SPY"], at(MON, "07:30"))["symbols"]["SPY"]
    assert out["previous_session"]["date"] == "2026-10-29" and out["premarket"]["change_pct"] == -1.0
    assert ("SPY", FRI) not in [(s, d) for s, d, _ in feed["reads"]]  # a closed day is never read


def test_after_hours_is_against_todays_close_and_an_early_close_moves_the_line(feed):
    feed["hours"][TUE] = {"status": "open", "open": 570, "close": 780}  # 13:00 close
    feed["days"][("AMD", TUE)] = rows(TUE, ("12:59", 250.0, 900), ("13:30", 245.0, 400))
    out = x.extended(["AMD"], at(TUE, "14:00"))
    assert out["phase"] == "after-hours"
    today = out["symbols"]["AMD"]["today"]
    assert today["regular_close"] == 250.0 and today["after_hours"]["change_pct"] == -2.0


def test_a_weekend_shows_the_last_sessions_after_hours(feed):
    feed["days"][("SMH", FRI)] = rows(FRI, ("15:59", 500.0, 100), ("17:00", 510.0, 100))
    out = x.extended(["SMH"], at(SAT, "11:00"))["symbols"]["SMH"]
    assert out["last_session"]["date"] == "2026-10-30" and out["last_session"]["after_hours"]["change_pct"] == 2.0


def test_before_four_no_request_goes_out_for_today(feed):
    feed["days"][("QQQ", MON)] = rows(MON, ("15:59", 680.0, 100), ("18:00", 676.6, 100))
    out = x.extended(["QQQ"], at(TUE, "02:00"))["symbols"]["QQQ"]
    assert out["last_session"]["after_hours"]["change_pct"] == -0.5
    assert all(day != TUE for _, day, _ in feed["reads"])  # Tradier refuses a start in the future
    assert {keep for _, day, keep in feed["reads"]} == {False}  # past sessions stay out of the Charts tab's cache


def test_regular_hours_add_nothing_and_a_failed_read_is_unavailable(feed):
    assert x.extended(["SPY"], at(TUE, "11:00")) is None
    feed["fail"].add("SPY")
    assert x.extended(["SPY"], at(TUE, "17:00"))["symbols"]["SPY"]["state"] == "unavailable"


def test_no_trades_is_said_not_a_zero(feed):
    feed["days"][("NBIS", MON)] = rows(MON, ("15:59", 100.0, 100))
    out = x.extended(["NBIS"], at(TUE, "08:00"))["symbols"]["NBIS"]
    assert out["premarket"] == {"state": "no_trades"} and out["previous_session"]["after_hours"] == {"state": "no_trades"}


def test_get_quotes_carries_extended_off_hours_within_the_result_limit(feed, monkeypatch):
    names = ["AAPL", "MSFT", "NVDA", "AMD", "AVGO", "TSM", "META", "GOOGL"]
    for s in names:
        feed["days"][(s, MON)] = rows(MON, ("15:59", 123.45, 100), ("16:30", 124.56, 2000), ("19:59", 125.67, 3000))
        feed["days"][(s, TUE)] = rows(TUE, ("04:01", 126.78, 100), ("09:00", 127.89, 4000))
    monkeypatch.setattr(feed_module.chart_feed, "quote_rows", lambda symbols: (
        [{"symbol": s, "last": 123.45, "change_percentage": 0.0, "volume": 123456789, "previous_close": 120.0,
          "day_high": 125.5, "day_low": 121.25, "trade_time": at(MON, "16:00").timestamp()} for s in symbols], 0.0, None))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at(TUE, "09:10").astimezone(tz)
    monkeypatch.setattr(copilot_tools, "datetime", Clock)
    out = copilot_tools.LiveEvidence().get_quotes(names)
    assert out["extended"]["phase"] == "pre-market" and out["extended"]["symbols"]["GOOGL"]["premarket"]["change_pct"] == 3.6
    text = copilot_tools.bounded(out)
    assert "[truncated]" not in text and json.loads(text)


def test_the_pre_market_pilots_scan_is_ranked_by_its_move_against_spy(tmp_path, monkeypatch):
    from app.engine import radar_premarket
    radar = tmp_path / "radar.sqlite"
    assert x.premarket_scan(str(radar), TUE)["state"] == "off"
    monkeypatch.setenv("RADAR_PREMARKET_ENABLED", "true")
    assert x.premarket_scan(str(radar), TUE)["state"] == "none"
    store = radar_premarket.PremarketStore(radar_premarket.store_path(radar))
    scan = {"session_date": "2026-11-03", "checkpoint": "08:50", "started_at": "s", "finished_at": "f", "rule_version": "radar-premarket-v0",
            "universe_version": "u", "status": "ok", "symbols_requested": 3, "symbols_read": 3, "symbols_with_bars": 3,
            "requests_used": 4, "flagged": 1, "error": None, "skip_reason": None}

    def reading(symbol, change, excess, flagged=False):
        return {"symbol": symbol, "prev_close": 10.0, "quote_last": 10.0, "quote_trade_ms": 0, "last": 10.0, "last_bar_at": "08:49",
                "bars": 5, "volume": 1000, "dollar_volume": 300_000.0, "change_pct": change, "excess_pct": excess, "flagged": flagged,
                "read_error": None}
    store.append_scan(scan, [reading("SPY", 0.5, 0.0), reading("AMD", 6.2, 5.7, True), reading("MRVL", -2.0, -2.5)])
    out = x.premarket_scan(str(radar), TUE)
    assert (out["checkpoint"], out["up"], out["down"], out["flagged"]) == ("08:50", 2, 1, ["AMD"])
    assert [m["symbol"] for m in out["movers"]] == ["AMD", "MRVL", "SPY"]
    assert x.premarket_scan(str(radar), MON)["state"] == "none"


def test_a_past_session_is_read_once_and_kept_out_of_the_charts_cache(feed):
    feed["days"][("SPY", MON)] = rows(MON, ("15:59", 700.0, 100), ("16:30", 707.0, 100))
    feed["days"][("SPY", TUE)] = rows(TUE, ("08:00", 714.0, 100))
    for minute in ("08:10", "08:20"):
        x.extended(["SPY"], at(TUE, minute))
    assert [(day, keep) for _, day, keep in feed["reads"]] == [(MON, False), (TUE, True), (TUE, True)]


def test_an_empty_past_read_is_not_remembered(feed):
    feed["days"][("SPY", TUE)] = rows(TUE, ("08:00", 714.0, 100))
    x.extended(["SPY"], at(TUE, "08:10"))
    feed["days"][("SPY", MON)] = rows(MON, ("15:59", 700.0, 100))
    assert x.extended(["SPY"], at(TUE, "08:20"))["symbols"]["SPY"]["premarket"]["change_pct"] == 2.0
