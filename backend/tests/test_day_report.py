"""The desk's day report, the server's part (engine/day_report.py, GET /copilot/desk/day-report, GET
/copilot/desk/pings?day_only): checked calls scored from the price when he checked to the close, the 30-day total,
tickers he does not follow left out, and today's entries with how many had a plan first. No network."""
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.database import get_session
from app.engine import call_check, day_report
from app.engine.chart_math import ET
from app.models import DayJournalEntry, TradeCapture
from app.routers import copilot_desk
from tests.test_exit_habits import engine  # noqa: F401

TODAY = date(2026, 11, 11)
EVENING = datetime(2026, 11, 11, 17, 0, tzinfo=ET).timestamp()  # 17:00 New York, after the close


@pytest.fixture(autouse=True)
def fresh_caches():
    day_report._scored.clear()
    day_report._closes.clear()


def reading(symbol="QQQ", side="put", expiry="2026-11-11", strike=660.0):
    return {"ticker": symbol, "expiry": expiry, "strike": strike, "side": side, "entry": None, "stop": None, "target": None}


def quote(price=660.0, mid=2.0, simulated=False):
    return {"as_of": "x", "underlying": {"last": price}, "contract": {"state": "ok", "mid": mid} if mid else None,
            **({"simulated": True} if simulated else {})}


def make(db_engine, symbol="QQQ", *, day=TODAY, hour=10, side="put", price=660.0, mid=2.0, passed=False, simulated=False,
         contract=True, **extra):
    when = datetime(day.year, day.month, day.day, hour, 5, tzinfo=ET)
    read = reading(symbol, side, strike=660.0 if contract else None, expiry="2026-11-11" if contract else None)
    shown = call_check.save("raw " + symbol, "desk", read, "Draft", {"headline": "h", "tiles": [], "against": None, "changes_if": None,
                                                                 "others": [], "note": None},
                            quote(price, mid, simulated) if price else None, None, when, db_engine)
    if passed:
        with Session(db_engine) as db:
            call_check.pass_check(db, shown["id"])
    return shown


def closes(monkeypatch, table: dict, contract: dict | None = None):
    monkeypatch.setattr(day_report, "underlying_close", lambda symbol, day, now: table.get(symbol))
    monkeypatch.setattr(day_report, "contract_close", lambda symbol, read, day, now: (contract or {}).get(symbol))


def report(db_engine, hidden=frozenset()):
    with Session(db_engine) as db:
        return day_report.checks_report(db, TODAY, EVENING, set(hidden))


def test_a_call_is_scored_from_the_price_when_he_checked_to_the_close(engine, monkeypatch):  # noqa: F811
    make(engine, "NVDA", side="call", price=100.0, mid=None, contract=False)
    make(engine, "QQQ", side="put", price=660.0, mid=2.0)
    closes(monkeypatch, {"NVDA": 103.0, "QQQ": 655.0}, {"QQQ": 3.0})
    rows = {r["symbol"]: r for r in report(engine)["rows"]}
    assert rows["NVDA"]["stock"] == {"at_check": 100.0, "close": 103.0, "pct": 3.0}
    assert rows["NVDA"]["way"] == "up" and rows["NVDA"]["basis"] == "stock" and rows["NVDA"]["contract"] is None
    assert rows["NVDA"]["contract_note"] == "no contract identified"
    assert rows["QQQ"]["contract"] == {"at_check": 2.0, "close": 3.0, "pct": 50.0}
    assert rows["QQQ"]["way"] == "up" and rows["QQQ"]["basis"] == "contract"


def test_a_down_call_and_a_put_read_the_way_the_call_was_for(engine, monkeypatch):  # noqa: F811
    make(engine, "AAPL", side="call", price=200.0, mid=None, contract=False)
    make(engine, "QQQ", side="put", price=660.0, mid=None, contract=False)  # the stock fell: a put is up
    closes(monkeypatch, {"AAPL": 196.0, "QQQ": 650.0})
    rows = {r["symbol"]: r for r in report(engine)["rows"]}
    assert rows["AAPL"]["way"] == "down" and rows["AAPL"]["stock"]["pct"] == -2.0
    assert rows["QQQ"]["way"] == "up" and rows["QQQ"]["stock"]["pct"] < 0


def test_a_contract_without_a_stored_quote_or_close_falls_back_to_the_stock_and_says_so(engine, monkeypatch):  # noqa: F811
    make(engine, "QQQ", side="call", price=660.0, mid=None)  # identified, but no quote was stored
    make(engine, "SPY", side="call", price=500.0, mid=1.5)  # a quote was stored, no close for the contract
    closes(monkeypatch, {"QQQ": 666.6, "SPY": 495.0})
    rows = {r["symbol"]: r for r in report(engine)["rows"]}
    assert rows["QQQ"]["contract_note"] == "no contract quote stored at the check" and rows["QQQ"]["way"] == "up"
    assert rows["SPY"]["contract_note"] == "no contract close stored" and rows["SPY"]["way"] == "down"


def test_either_price_missing_is_not_measured_with_the_reason(engine, monkeypatch):  # noqa: F811
    make(engine, "NOPX", price=None)  # no price stored when he checked
    make(engine, "NOCLOSE", price=50.0)  # no closing price stored
    make(engine, "SIM", price=50.0, simulated=True)
    make(engine, "LATE", hour=16, price=50.0)  # checked after the 16:00 close
    closes(monkeypatch, {"SIM": 51.0, "LATE": 51.0})
    rows = {r["symbol"]: r for r in report(engine)["rows"]}
    assert {k: (r["state"], r["way"]) for k, r in rows.items()} == {k: ("not_measured", None) for k in ("NOPX", "NOCLOSE", "SIM", "LATE")}
    assert "no price was stored" in rows["NOPX"]["why"] and "no closing price" in rows["NOCLOSE"]["why"]
    assert "simulated" in rows["SIM"]["why"] and "after the close" in rows["LATE"]["why"]


def test_a_passed_call_is_scored_the_same_flat_way(engine, monkeypatch):  # noqa: F811
    make(engine, "NVDA", side="call", price=100.0, mid=None, contract=False, passed=True)
    make(engine, "AMD", side="call", price=100.0, mid=None, contract=False)
    closes(monkeypatch, {"NVDA": 110.0, "AMD": 110.0})
    rows = {r["symbol"]: r for r in report(engine)["rows"]}
    assert rows["NVDA"]["decision"] == "passed" and rows["AMD"]["decision"] == "neither"
    assert {k: (r["way"], r["stock"]) for k, r in rows.items() if k == "NVDA"} == {"NVDA": ("up", rows["AMD"]["stock"])}
    assert not {"missed", "gain", "left"} & set(json.dumps(rows["NVDA"]).lower().replace('"', " ").split())


def test_a_saved_plan_reads_as_planned(engine, monkeypatch):  # noqa: F811
    from tests.test_exit_habits import ROTH
    made = make(engine, "NVDA", side="call", price=100.0, mid=None, contract=False)
    with Session(engine) as db:
        db.add(TradeCapture(client_id="cc1", received_at=datetime(2026, 11, 11, 16), account_id=ROTH, account_label="Roth",
                            underlying="NVDA", side="buy_calls", instrument="option", mode="discretionary",
                            context_state="unavailable", image_state="none", origin_kind="checked_call", origin_ref=made["id"],
                            context_json="{}"))
        db.commit()
    closes(monkeypatch, {"NVDA": 101.0})
    assert report(engine)["rows"][0]["decision"] == "planned"


def test_the_thirty_day_total_leads_and_today_is_counted_within_it(engine, monkeypatch):  # noqa: F811
    for n in range(3):  # three earlier days, one check each
        make(engine, "AAA", day=TODAY - timedelta(days=n + 1), side="call", price=10.0, mid=None, contract=False)
    make(engine, "BBB", side="call", price=10.0, mid=None, contract=False)  # today, up
    make(engine, "CCC", side="call", price=10.0, mid=None, contract=False)  # today, down
    make(engine, "DDD", side="call", price=10.0, mid=None, contract=False)  # today, not measured
    make(engine, "OLD", day=TODAY - timedelta(days=45), side="call", price=10.0, mid=None, contract=False)  # outside the window
    monkeypatch.setattr(day_report, "underlying_close",
                        lambda symbol, day, now: {"AAA": 11.0, "BBB": 12.0, "CCC": 9.0, "OLD": 12.0}.get(symbol))
    monkeypatch.setattr(day_report, "contract_close", lambda *a: None)
    body = report(engine)
    assert body["today"] == {"checked": 3, "up": 1, "down": 1, "flat": 0, "not_measured": 1}
    assert body["window"] == {"days": 30, "checked": 6, "up": 4, "down": 1, "flat": 0, "not_measured": 1}
    assert sorted(r["symbol"] for r in body["rows"]) == ["BBB", "CCC", "DDD"]  # today's only


def test_a_ticker_he_does_not_follow_stays_out_of_the_rows_and_the_total(engine, monkeypatch):  # noqa: F811
    make(engine, "NVDA", side="call", price=100.0, mid=None, contract=False)
    make(engine, "OLDX", side="call", price=100.0, mid=None, contract=False)
    make(engine, "OLDX", day=TODAY - timedelta(days=2), side="call", price=100.0, mid=None, contract=False)
    closes(monkeypatch, {"NVDA": 101.0, "OLDX": 101.0})
    body = report(engine, hidden={"OLDX"})
    assert [r["symbol"] for r in body["rows"]] == ["NVDA"]
    assert body["window"]["checked"] == 1


def test_no_checks_is_an_empty_report(engine):  # noqa: F811
    body = report(engine)
    assert body["rows"] == [] and body["today"]["checked"] == 0 and body["window"]["checked"] == 0


def test_a_finished_days_measured_score_is_kept_but_an_unmeasured_one_is_asked_again(engine, monkeypatch):  # noqa: F811
    old = make(engine, "AAA", day=TODAY - timedelta(days=1), side="call", price=10.0, mid=None, contract=False)
    seen = []
    monkeypatch.setattr(day_report, "contract_close", lambda *a: None)
    monkeypatch.setattr(day_report, "underlying_close", lambda s, d, n: seen.append(s) or None)
    report(engine)
    assert seen == ["AAA"]
    monkeypatch.setattr(day_report, "underlying_close", lambda s, d, n: seen.append(s) or 11.0)
    report(engine)
    report(engine)
    assert seen == ["AAA", "AAA"]  # measured once, then served from memory
    assert day_report._scored[old["id"]]["way"] == "up"


# ------------------------------------------------------------------ the closing price


def minutes(day, closes_by_hhmm):
    return [{"time": datetime.combine(day, datetime.strptime(t, "%H:%M").time(), ET).timestamp(), "close": c}
            for t, c in closes_by_hhmm.items()]


def test_the_close_is_the_last_regular_session_minute_from_the_disk_cache(monkeypatch):
    from app.engine import ping_images
    bars = minutes(TODAY, {"09:30": 10.0, "15:59": 12.5}) + minutes(TODAY, {"16:01": 99.0})  # after-hours is not the close
    monkeypatch.setattr(ping_images, "stored_bars", lambda symbol, day: bars)
    assert day_report.underlying_close("QQQ", TODAY, EVENING) == 12.5


def test_a_session_cut_short_in_the_cache_is_not_the_close(monkeypatch):
    from app.engine import ping_images
    monkeypatch.setattr(ping_images, "stored_bars", lambda symbol, day: minutes(TODAY, {"09:30": 10.0, "13:00": 11.0}))
    from app.engine.chart_feed import chart_feed
    monkeypatch.setattr(chart_feed, "peek_minutes", lambda symbol, day: None)
    assert day_report.underlying_close("QQQ", TODAY, EVENING) is None


def test_today_after_the_close_uses_cached_minutes_read_after_the_bell_and_never_before_it(monkeypatch):
    from app.engine import ping_images
    from app.engine.chart_feed import chart_feed
    monkeypatch.setattr(ping_images, "stored_bars", lambda symbol, day: [])
    bars = minutes(TODAY, {"15:59": 12.0})
    bell = datetime.combine(TODAY, datetime.strptime("16:00", "%H:%M").time(), ET).timestamp()
    monkeypatch.setattr(chart_feed, "peek_minutes", lambda symbol, day: (bars, bell - 30))  # read before the close
    assert day_report.underlying_close("QQQ", TODAY, EVENING) is None
    monkeypatch.setattr(chart_feed, "peek_minutes", lambda symbol, day: (bars, bell + 60))
    assert day_report.underlying_close("QQQ", TODAY, EVENING) == 12.0
    assert day_report.underlying_close("QQQ", TODAY, bell - 600) == 12.0  # kept; no second read needed


def test_before_the_close_today_is_not_measured(monkeypatch):
    from app.engine import ping_images
    from app.engine.chart_feed import chart_feed
    monkeypatch.setattr(ping_images, "stored_bars", lambda symbol, day: [])
    monkeypatch.setattr(chart_feed, "peek_minutes", lambda symbol, day: pytest.fail("no cache read before the close"))
    assert day_report.underlying_close("QQQ", TODAY, datetime(2026, 11, 11, 11, 0, tzinfo=ET).timestamp()) is None


# ------------------------------------------------------------------ the routes


@pytest.fixture
def desk(engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(copilot_desk.today, "_now", lambda: EVENING)
    app = FastAPI()
    app.include_router(copilot_desk.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def test_the_route_reads_checks_and_entries_and_hides_a_ticker_he_does_not_follow(desk, engine, monkeypatch):  # noqa: F811
    make(engine, "NVDA", side="call", price=100.0, mid=None, contract=False)
    make(engine, "OLDX", side="call", price=100.0, mid=None, contract=False)
    closes(monkeypatch, {"NVDA": 98.0, "OLDX": 98.0})
    with Session(engine) as db:
        db.add(DayJournalEntry(day=TODAY, kind="follow", symbol="OLDX", text="Not following", operation_id="f1"))
        db.commit()
    monkeypatch.setattr(day_report, "entries_today", lambda db, day, hidden: {"state": "ok", "entries": 2, "planned": 1, "late": 0, "pending": 0})
    body = desk.get("/copilot/desk/day-report").json()
    assert body["day"] == "2026-11-11" and body["sections"] == {"entries": "ok", "checks": "ok"}
    assert [r["symbol"] for r in body["checks"]["rows"]] == ["NVDA"]
    assert body["checks"]["window"]["checked"] == 1
    assert body["entries"]["entries"] == 2 and body["entries"]["planned"] == 1


def test_a_failing_part_does_not_take_the_other_down(desk, engine, monkeypatch):  # noqa: F811
    def boom(*a):
        raise RuntimeError("no")
    monkeypatch.setattr(day_report, "checks_report", boom)
    monkeypatch.setattr(day_report, "entries_today", lambda db, day, hidden: {"state": "ok", "entries": 0, "planned": 0, "late": 0, "pending": 0})
    body = desk.get("/copilot/desk/day-report").json()
    assert body["checks"] is None and body["sections"]["checks"] == "unavailable" and body["entries"]["entries"] == 0


def test_the_route_is_refused_while_the_lab_is_off(desk, monkeypatch):
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/day-report").status_code == 503


def test_entries_count_today_and_how_many_had_a_plan_before_the_fill(engine, monkeypatch):  # noqa: F811
    from app.engine import plan_streak
    start = datetime(2026, 11, 11, 0, 0, tzinfo=ET).timestamp()

    def entry(short, state, hour):
        return {"short": short, "state": state, "entry_time": start + hour * 3600, "trade_id": short}
    rows = [entry("NBIS 100C", "planned", 10), entry("OLDX 5C", "planned", 11), entry("MU 90P", "unplanned", 12),
            entry("AMD 150C", "late", 13), entry("SPY stock", "planned", -20)]  # the last one is yesterday's
    monkeypatch.setattr(plan_streak, "streak", lambda db: {"this_week": {"entries": rows}})
    with Session(engine) as db:
        body = day_report.entries_today(db, TODAY, {"OLDX"})
    assert {k: v for k, v in body.items() if k != "rows"} == {"state": "ok", "entries": 3, "planned": 1, "late": 1, "pending": 0}
    assert [r["contract"] for r in body["rows"]] == ["NBIS 100C", "MU 90P", "AMD 150C"]  # in the order he entered


def test_the_pings_read_can_be_cut_to_today_and_leaves_a_ticker_he_does_not_follow_out(desk, engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk, "_alert_outcomes", lambda db, now, first, start: {"state": "ok", "rows": [
        {"symbol": "NBIS", "contract": "NBIS 11/21/26 100C", "at": 1}, {"symbol": "OLDX", "contract": "OLDX 11/21/26 5C", "at": 2}]})
    monkeypatch.setattr(copilot_desk, "_radar_outcomes", lambda db, now, first, start: {"state": "ok", "rows": [
        {"symbol": "OLDX", "event_id": "a"}, {"symbol": "MU", "event_id": "b"}]})
    with Session(engine) as db:
        db.add(DayJournalEntry(day=TODAY, kind="follow", symbol="OLDX", text="Not following", operation_id="f1"))
        db.commit()
    body = desk.get("/copilot/desk/pings", params={"day_only": "true"}).json()
    assert body["since"] == "2026-11-11"
    assert [r["symbol"] for r in body["alerts"]["rows"]] == ["NBIS"] and [r["symbol"] for r in body["radar"]["rows"]] == ["MU"]


def test_the_feeds_peek_at_what_they_hold_and_never_request(monkeypatch):
    from app.engine import tradier
    from app.engine.chart_feed import CachedRead, ChartFeed
    feed = ChartFeed()
    assert feed.peek_minutes("QQQ", TODAY) is None  # nothing cached: no request is made to find out
    params = {"symbol": "QQQ", "interval": "1min", "session_filter": "all", "start": "2026-11-11 04:00", "end": "2026-11-11 20:00"}
    stamp = datetime(2026, 11, 11, 16, 5, tzinfo=ET).timestamp()
    row = {"time": "2026-11-11T15:59:00", "timestamp": int(datetime(2026, 11, 11, 15, 59, tzinfo=ET).timestamp()),
           "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10, "price": 1.5, "vwap": 1.5}
    feed._cache[(tradier.TRADIER_BASE_URL, "/v1/markets/timesales", tuple(sorted(params.items())))] = CachedRead(
        {"series": {"data": [row]}}, stamp, stamp - 1)  # expired: still the last read
    bars, fetched = feed.peek_minutes("QQQ", TODAY)
    assert fetched == stamp and bars and bars[-1]["close"] == 1.5
