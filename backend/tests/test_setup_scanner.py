"""Setup scanner S1: the pure rules, and the watcher's candidates, paper trades and restarts."""

import json
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import scanner_rules as rules
from app.engine import setup_scanner
from app.engine.options_models import OptionContract
from app.models import Account, Fill, Trade, ScannerCandidate, ScannerEvent
from app.routers import scanner as routes

ET = ZoneInfo("America/New_York")
DAY = date(2026, 10, 7)  # a Wednesday


def at(hour, minute, second=0, day=DAY):
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ET).timestamp())


OPEN, CLOSE = at(9, 30), at(16, 0)


def bar(start_minute, o, h, lo, c, v=100, vwap=100.0, ema9=100.0):
    start = OPEN + start_minute * 60
    return {"start": start, "end": start + 300, "open": o, "high": h, "low": lo, "close": c, "volume": v, "vwap": vwap, "ema9": ema9}


def contract(side="call", delta=0.35, bid=1.0, ask=1.05, oi=1000, volume=500, strike=101.0, expiration=DAY, multiplier=100):
    letter = "C" if side == "call" else "P"
    return OptionContract(f"SPY{expiration:%y%m%d}{letter}{int(strike * 1000):08d}", "SPY", "SPY", expiration, side, strike,
                          multiplier, bid, ask, None, None, None, volume, oi, None, None, None, None, None,
                          delta if side == "call" else -delta, None, None, None, None)


# ------------------------------------------------------------------ rules


def test_five_minute_bars_build_session_vwap_and_skip_extended_hours():
    minutes = [{"time": OPEN - 60, "end_time": OPEN, "open": 50, "high": 50, "low": 50, "close": 50, "volume": 1000}]
    minutes += [{"time": OPEN + i * 60, "end_time": OPEN + i * 60 + 60, "open": 100 + i, "high": 100 + i, "low": 100 + i,
                 "close": 100 + i, "volume": 100} for i in range(10)]
    bars = rules.five_minute_bars(minutes, OPEN, CLOSE)
    assert [b["start"] for b in bars] == [OPEN, OPEN + 300]
    assert bars[0]["open"] == 100 and bars[0]["close"] == 104 and bars[0]["high"] == 104 and bars[0]["volume"] == 500
    assert bars[0]["vwap"] == pytest.approx(102)  # the premarket print is excluded
    assert bars[1]["vwap"] == pytest.approx(104.5)


def opening(price=100.0, v=100):
    return [bar(m, price, price + 0.5, price - 0.5, price, v) for m in (0, 5, 10)]


def test_opening_range_break_needs_vwap_volume_and_the_1045_cutoff():
    last = at(15, 0)
    good = opening() + [bar(15, 100.2, 100.9, 100.1, 100.8, v=150)]
    [signal] = rules.scan(good, 2.0, OPEN, last, set())
    assert (signal["setup"], signal["direction"], signal["bar_end"]) == ("orb", "long", at(9, 50))
    assert signal["stop"] == pytest.approx(100.0) and signal["target"] == pytest.approx(102.4)
    assert rules.scan(opening() + [bar(15, 100.2, 100.9, 100.1, 100.8, v=50)], 2.0, OPEN, last, set()) == []
    late = opening() + [bar(m, 100, 100.4, 99.9, 100.2) for m in range(15, 75, 5)] + [bar(75, 100.2, 100.9, 100.1, 100.8, v=150)]
    assert rules.scan(late, 2.0, OPEN, last, set()) == []  # the first break closed at 10:50
    # Only the first close above the range counts, even when it failed a filter.
    again = opening() + [bar(15, 100.2, 100.9, 100.1, 100.8, v=50), bar(20, 100.8, 101.0, 100.7, 100.9, v=150)]
    assert rules.scan(again, 2.0, OPEN, last, set()) == []


def fade_day():
    # ATR 2: stretched means a low at or below VWAP - 0.7.
    return opening() + [bar(15, 99.8, 99.9, 99.6, 99.7), bar(20, 99.6, 99.3, 99.2, 99.25),
                        bar(25, 99.3, 99.5, 99.3, 99.45)]


def test_fade_turns_back_toward_vwap_with_reward_at_least_risk():
    [signal] = rules.scan(fade_day(), 2.0, OPEN, at(15, 0), set())
    assert (signal["setup"], signal["direction"], signal["bar_end"]) == ("fade", "long", at(10, 0))
    assert signal["stop"] == pytest.approx(99.1) and signal["target"] == pytest.approx(100.0)
    assert signal["facts"]["daily_atr14"] == 2.0 and signal["flags"] == []


def test_a_saved_fade_resets_the_stretch_and_two_saved_fades_end_the_day():
    day = fade_day() + [bar(30, 99.45, 99.6, 99.45, 99.55)]
    saved = {("fade", at(10, 0))}
    assert [s["bar_end"] for s in rules.scan(day, 2.0, OPEN, at(15, 0), saved)] == [at(10, 0)]
    unsaved = rules.scan(day, 2.0, OPEN, at(15, 0), set())
    assert [s["bar_end"] for s in unsaved] == [at(10, 0), at(10, 5)]


def test_short_fade_flags_an_extended_put():
    day = opening() + [bar(15, 100.2, 101.0, 100.2, 100.9, v=50), bar(20, 100.9, 101.0, 100.85, 100.9, ema9=100.0),
                       bar(25, 100.85, 100.85, 100.6, 100.7, ema9=101.6)]
    [signal] = rules.scan(day, 1.0, OPEN, at(15, 0), set())
    assert (signal["setup"], signal["direction"]) == ("fade", "short")
    assert signal["flags"] == ["put_extended"]  # already 0.9% below its EMA9


def test_nothing_after_the_last_bar_end():
    assert rules.scan(fade_day(), 2.0, OPEN, at(9, 55), set()) == []


def test_contract_choice_and_expiration_rule():
    assert rules.pick_expiration([date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 16)], DAY) is None  # only 1-2 or 9 days
    assert rules.pick_expiration([date(2026, 10, 9), date(2026, 10, 12)], DAY) == date(2026, 10, 12)
    assert rules.pick_expiration([DAY, date(2026, 10, 12)], DAY) == DAY
    chosen = rules.choose_contract([
        contract(delta=0.30, strike=102), contract(delta=0.36, strike=101), contract(delta=0.35, oi=100, strike=100),
        contract(delta=0.35, bid=1.0, ask=1.3, strike=99), contract(side="put", delta=0.35, strike=98),
    ], "long")
    assert chosen["strike"] == 101 and chosen["delta"] == 0.36
    assert rules.choose_contract([contract(delta=0.5), contract(multiplier=None)], "long") is None
    assert rules.choose_contract([contract(side="put", delta=0.3)], "short")["option_type"] == "put"


def minute(t, low, high):
    return {"time": t, "end_time": t + 60, "open": low, "high": high, "low": low, "close": low, "volume": 1}


def test_exit_condition_stop_first_and_clock_exits():
    entry = at(10, 0, 20)
    bars = [minute(at(10, 0), 90, 110), minute(at(10, 1), 99.0, 103.0)]  # the entry minute itself is not judged
    found = rules.exit_condition("long", 99.0, 103.0, bars, entry, entry + 3600, at(15, 45), at(10, 3), 30)
    assert found["reason"] == "stop" and found["condition_at"] == at(10, 2)
    assert rules.exit_condition("long", 99.0, 103.0, bars[:1], entry, entry + 3600, at(15, 45), at(10, 3), 30) is None
    assert rules.exit_condition("long", 99.0, 103.0, [], entry, entry + 3600, at(15, 45), entry + 3600, 30)["reason"] == "time_stop"
    found = rules.exit_condition("short", 101.0, 99.0, [minute(at(10, 1), 98.5, 100)], entry, entry + 3600, at(15, 45), at(10, 3), 30)
    assert found["reason"] == "target"


def test_result_is_ask_in_bid_out_with_commission():
    out = rules.result({"ask": 1.05, "bid": 1.0}, {"bid": 1.5, "ask": 1.6}, 100)
    assert out["pnl"] == pytest.approx(43.7)
    assert out["pnl_2x_spread"] == pytest.approx((1.45 - 1.075) * 100 - 1.3)
    assert out["return_on_premium"] == pytest.approx(43.7 / 105.65, abs=1e-4)


def test_params_hash_is_stable():
    assert rules.PARAMS["fade"]["stretch_atr"] == 0.35 and len(rules.PARAMS_HASH) == 64


# ------------------------------------------------------------------ the watcher


class Calendar:
    def hours(self, day):
        return {"date": day.isoformat(), "status": "open", "open": 570, "close": 960}


class Feed:
    def __init__(self):
        self.minutes = []

    def add(self, first, last, low, high, volume=100):
        self.minutes += [(t, low, high, volume) for t in range(first, last, 60)]

    def read(self, path, params, ttl):
        if path == "/v1/markets/history":
            days = [{"date": f"2026-09-{d:02d}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1} for d in range(10, 30)]
            return {"history": {"day": days}}, 0, None
        rows = [{"timestamp": t, "open": low, "high": high, "low": low, "close": high, "volume": v} for t, low, high, v in self.minutes]
        return {"series": {"data": rows}}, 0, None


class Options:
    def __init__(self):
        self.chains = 0

    def expirations(self, symbol):
        return [DAY]

    def chain(self, symbol, expiration):
        self.chains += 1
        return SimpleNamespace(contracts=(contract(),))


class Quotes:
    def __init__(self):
        self.next = (1.0, 1.05)
        self.updated_ms = 10**15  # both sides updated after any decision in these tests

    def __call__(self, occ):
        if self.next is None:
            return None
        bid, ask = self.next
        return SimpleNamespace(bid=bid, ask=ask, bid_date=self.updated_ms, ask_date=self.updated_ms)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(rules, "UNIVERSE", ("SPY",))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def breakout_day(feed):
    feed.add(OPEN, at(9, 45), 99.5, 100.5)  # opening range 99.5 - 100.5, ATR 2
    feed.add(at(9, 45), at(9, 50), 100.4, 100.9, volume=150)  # closes 100.9 above the range and VWAP


def scanner(engine, now, quotes=None, options=None):
    clock = Clock(now)
    return setup_scanner.SetupScanner(engine, Feed(), Calendar(), options or Options(), clock, quote=quotes or Quotes()), clock


def rows(engine):
    with Session(engine) as db:
        cands = db.exec(select(ScannerCandidate)).all()
        events = db.exec(select(ScannerEvent)).all()
        return cands, {e.event_type: json.loads(e.data_json) for e in events}


def test_breakout_is_saved_entered_and_exits_at_target(engine):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    cands, events = rows(engine)
    assert len(cands) == 1 and cands[0].setup == "orb" and cands[0].stop == pytest.approx(100.0)
    assert json.loads(cands[0].contract_json)["strike"] == 101.0 and events["entry"]["ask"] == 1.05

    watch.run()  # the same bar again
    again, _ = scanner(engine, at(9, 50, 50))  # and a restarted process
    again.feed = watch.feed
    again.run()
    assert len(rows(engine)[0]) == 1

    target = cands[0].target
    watch.feed.add(at(9, 51), at(9, 52), 100.9, target + 0.1)
    watch.quote.next = (1.5, 1.6)
    clock.now = at(9, 52, 40)
    watch.run()
    _, events = rows(engine)
    assert events["exit_intent"]["reason"] == "target" and events["exit"]["pnl"] == pytest.approx(43.7)

    with Session(engine) as db:
        view = setup_scanner.day_view(db, DAY, [])
    assert view["totals"]["resolved"] == 1 and view["candidates"][0]["status"] == "exit"


def test_no_quote_for_two_minutes_is_unresolved(engine):
    quotes = Quotes()
    quotes.next = None
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    assert "entry" not in rows(engine)[1]
    clock.now = at(9, 52, 40)
    watch.run()
    assert rows(engine)[1]["unresolved"]["reason"] == "no entry quote within two minutes"


def test_a_quote_that_arrives_after_the_window_is_never_used(engine):
    quotes = Quotes()
    quotes.next = None
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    quotes.next = (1.0, 1.05)  # the provider recovers half an hour later
    clock.now = at(10, 20)
    watch.run()
    events = rows(engine)[1]
    assert "entry" not in events and events["unresolved"]["reason"] == "no entry quote within two minutes"


def test_a_quote_not_updated_since_the_decision_is_not_a_fill(engine):
    quotes = Quotes()
    quotes.updated_ms = (at(9, 50, 0)) * 1000  # last changed before the setup was saved
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    assert "entry" not in rows(engine)[1]
    quotes.updated_ms = at(9, 51) * 1000
    clock.now = at(9, 51, 5)
    watch.run()
    assert rows(engine)[1]["entry"]["ask"] == 1.05


def test_an_exit_quote_after_the_window_is_unresolved(engine):
    quotes = Quotes()
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    watch.feed.add(at(9, 51), at(9, 52), 100.9, rows(engine)[0][0].target + 0.1)
    quotes.next = None
    clock.now = at(9, 52, 40)
    watch.run()
    assert "exit_intent" in rows(engine)[1]
    quotes.next = (1.5, 1.6)
    clock.now = at(10, 30)
    watch.run()
    events = rows(engine)[1]
    assert "exit" not in events and events["unresolved"]["reason"] == "no exit quote within two minutes"


def test_an_exit_noticed_late_is_unresolved_never_priced(engine):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    clock.now = at(11, 0)  # the 60-minute time stop passed at 10:50:35 while nothing was watching
    watch.run()
    events = rows(engine)[1]
    assert "exit" not in events and events["unresolved"]["reason"].startswith("monitoring gap")


def test_no_contract_is_saved_without_a_trade(engine):
    options = Options()
    options.expirations = lambda symbol: [date(2026, 10, 8)]
    watch, _ = scanner(engine, at(9, 50, 35), options=options)
    breakout_day(watch.feed)
    watch.run()
    cands, events = rows(engine)
    assert cands[0].contract_json is None and events == {}
    assert json.loads(cands[0].facts_json)["contract_note"].startswith("no expiration")


def test_a_bar_noticed_late_is_skipped(engine):
    watch, _ = scanner(engine, at(9, 53, 0))
    breakout_day(watch.feed)
    watch.run()
    assert rows(engine)[0] == []


def test_day_route_marks_a_sixth_entry(engine):
    watch, _ = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    with Session(engine) as db:
        account = Account(name="Roth", type="roth_ira", last4="0000")
        db.add(account)
        for i in range(5):
            db.add(Trade(account_id=account.id, ticker="SPY", instrument_type="option", contracts=1, avg_entry_premium=1.0,
                         total_premium_paid=100.0, opened_at=datetime(2026, 10, 7, 9, 31 + i)))
        # A sixth fill of an already-open trade is not another entry.
        db.add(Fill(account_id=account.id, ticker="SPY", instrument_type="option", side="buy_to_open", contracts=1, price=1.0,
                    executed_at=datetime(2026, 10, 7, 9, 40), raw_email_id="scale-in"))
        db.commit()
    app = FastAPI()
    app.include_router(routes.router, prefix="/scanner")
    app.dependency_overrides[get_session] = lambda: Session(engine)
    body = TestClient(app).get("/scanner/day", params={"day": "2026-10-07"}).json()
    assert body["candidates"][0]["flags"] == ["sixth_plus_entry"] and body["scanner_version"] == "s1-v1"
    assert TestClient(app).get("/scanner/day", params={"day": "nope"}).status_code == 422
