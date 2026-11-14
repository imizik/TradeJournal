"""The QQQ intraday momentum paper book: hourly checks on the noise area, band-and-VWAP stops, quote fills, flat by 15:59."""

from __future__ import annotations

from datetime import date, datetime
import json

import pytest

from app.engine import intraday_momentum_book as ib
from app.engine.chart_math import ET
from app.engine.tradier import TradierQuote

DAY = "2026-11-16"  # a Monday
PREV = "2026-11-13"


def at(day: str, hh: int, mm: int, ss: int = 0) -> float:
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=ET).timestamp()


class Calendar:
    def __init__(self, close: int = 960):
        self.close = close

    def hours(self, day):
        return {"status": "open", "open": 570, "close": self.close}


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self):
        return self.t


class Feed:
    """Today's minute bars: flat at ``base`` from 09:30, with ``path`` setting the price from a minute on."""

    def __init__(self, clock: Clock, base: float = 100.0, path: dict[int, float] | None = None, volume: float = 1000.0):
        self.clock, self.base, self.path, self.volume = clock, base, dict(path or {}), volume

    def today_minutes(self, symbol, now):
        day = datetime.fromtimestamp(now, ET).date().isoformat()
        bars, p = [], self.base
        for m in range(570, 960):
            start = at(day, m // 60, m % 60)
            if start + 60 > now:
                break
            o = p
            if m in self.path:
                p = self.path[m]
            bars.append({"time": int(start), "open": o, "high": max(o, p), "low": min(o, p), "close": p, "volume": self.volume})
        return bars


def quotes(clock: Clock, spread: float = 0.02, calls: list | None = None, feed: Feed | None = None, prev: float = 100.0):
    def get(symbols):
        if calls is not None:
            calls.append(clock.t)
        last = feed.today_minutes("QQQ", clock.t)[-1]["close"] if feed else 100.0
        ms = int((clock.t - 1) * 1000)
        return {"QQQ": TradierQuote(symbol="QQQ", bid=round(last - spread / 2, 2), ask=round(last + spread / 2, 2), bid_date=ms, ask_date=ms,
                                    raw={"prevclose": prev})}
    return get


def seed(tmp_path, move: float = 0.004, close: float = 100.0, n: int = ib.LOOKBACK):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({"sessions": [{"day": f"2026-08-{k + 1:02d}" if k < 31 else f"2026-09-{k - 30:02d}",
                                              "open": 100.0, "close": close, "moves": {str(m): move for m in ib.CHECKS}}
                                             for k in range(n - 1)] + [{"day": PREV, "open": 100.0, "close": close,
                                                                        "moves": {str(m): move for m in ib.CHECKS}}]}))
    return path


def book(tmp_path, clock, feed, quote=None, calendar=None, seed_path=None):
    store = ib.Store(tmp_path / "book.sqlite3", seed=seed_path or seed(tmp_path))
    return ib.IntradayMomentumBook(calendar or Calendar(), feed, clock=clock, quote=quote or quotes(clock, feed=feed), store=store)


def run_until(b, clock, day, hh, mm, step=20):
    end = at(day, hh, mm)
    while clock.t <= end:
        b.run()
        clock.t += step


def test_long_at_the_10_oclock_check_above_band_and_vwap_then_flat_at_1559(tmp_path):
    # sigma 0.4%, VM 1.25: upper band 100.5. QQQ jumps to 101 at 09:40 and holds; VWAP stays below 101.
    clock = Clock(at(DAY, 9, 59, 30))
    feed = Feed(clock, path={580: 101.0})
    b = book(tmp_path, clock, feed)
    run_until(b, clock, DAY, 16, 1)
    trades = b.store.trades()
    assert len(trades) == 1
    t = trades[0]
    assert (t["side"], t["entry"], t["how"], t["exit"]) == (1, 101.01, "close", 100.99)
    assert datetime.fromtimestamp(t["entry_at"], ET).strftime("%H:%M") == "10:00"
    assert ib.bp(t) == pytest.approx((100.99 - 101.01) / 100.0 * 1e4)
    assert {c["minute"] for c in b.store.checks()} == set(ib.CHECKS)
    assert b.store.has_session(DAY)  # recorded after the close for tomorrow's window


def test_vwap_stop_then_short_below_the_lower_band(tmp_path):
    clock = Clock(at(DAY, 9, 59, 30))
    feed = Feed(clock, path={580: 101.0, 700: 100.6, 760: 99.0})
    b = book(tmp_path, clock, feed)
    run_until(b, clock, DAY, 15, 59, 30)
    hows = [(t["side"], t["how"]) for t in b.store.trades()]
    # Long at 10:00; at 12:00 the price (100.6) is above the band (100.5) but below VWAP (about 100.8): stopped;
    # short at 13:00 below the lower band (99.5); out at 15:59.
    assert hows == [(1, "stop"), (-1, "close")]


def test_no_trading_on_an_early_close_without_the_calendar_or_without_history(tmp_path):
    clock = Clock(at(DAY, 9, 59, 30))
    feed = Feed(clock, path={580: 101.0})
    b = book(tmp_path, clock, feed, calendar=Calendar(close=780))
    run_until(b, clock, DAY, 12, 0)
    assert b.store.trades() == [] and b.store.checks() == []
    nocal = ib.IntradayMomentumBook(None, feed, clock=clock, quote=quotes(clock, feed=feed),
                                    store=ib.Store(tmp_path / "nocal.sqlite3", seed=seed(tmp_path)))
    clock.t = at(DAY, 10, 0, 5)
    nocal.run()
    assert nocal.store.checks() == []
    thin = book(tmp_path / "thin", clock, feed, seed_path=seed(tmp_path, n=10))
    clock.t = at(DAY, 10, 0, 5)
    thin.run()
    assert thin.store.checks()[0]["status"] == "missed" and thin.store.trades() == []


def test_a_check_reached_late_is_missed_never_traded(tmp_path):
    clock = Clock(at(DAY, 10, 6))
    feed = Feed(clock, path={580: 101.0})
    b = book(tmp_path, clock, feed)
    b.run()
    assert b.store.checks()[0]["status"] == "missed" and b.store.trades() == []


def test_a_stale_quote_waits_and_one_check_never_trades_twice(tmp_path):
    clock, calls = Clock(at(DAY, 10, 0, 5)), []
    feed = Feed(clock, path={580: 101.0})

    def stale(symbols):
        calls.append(clock.t)
        ms = int((clock.t - 300) * 1000)
        return {"QQQ": TradierQuote(symbol="QQQ", bid=100.99, ask=101.01, bid_date=ms, ask_date=ms, raw={"prevclose": 100.0})}
    b = book(tmp_path, clock, feed, quote=stale)
    b.run()
    assert b.store.trades() == [] and b.store.checks() == []  # waits for a fresh quote
    b.quote = quotes(clock, feed=feed)
    for s in (20, 40, 60):
        clock.t = at(DAY, 10, 0, 5) + s
        b.run()
    assert len(b.store.trades()) == 1 and len(b.store.checks()) == 1


def test_a_position_left_open_by_an_outage_closes_at_the_next_pass(tmp_path):
    clock = Clock(at(DAY, 10, 0, 5))
    feed = Feed(clock, path={580: 101.0})
    b = book(tmp_path, clock, feed)
    b.run()
    clock.t = at("2026-11-17", 9, 0)
    b.run()
    assert b.store.trades()[0]["status"] == "open"  # not before the next session opens
    clock.t = at("2026-11-17", 9, 31, 30)
    b.run()
    assert b.store.trades()[0]["how"] == "late close"


def test_read_summarises_days_and_counts_checked_days_without_trades(tmp_path, monkeypatch):
    path = tmp_path / "book.sqlite3"
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_PATH", str(path))
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_ENABLED", "true")
    assert ib.read(0)["days"] == [] and not path.exists()
    store = ib.Store(path, seed=None)
    store.enter("2026-11-16", 1, 100.0, 1.0, 100.0)
    store.exit(1, 2.0, 101.0, "close")
    store.add_check("2026-11-16", 600, "done")
    store.add_check("2026-11-17", 600, "done")  # a day with no trade
    store.enter("2026-11-18", -1, 100.0, 3.0, 100.0)
    store.add_check("2026-11-18", 600, "done")  # today, in progress with an open position: not a day yet
    view = ib.read(at("2026-11-18", 11, 0))
    assert [d["day"] for d in view["days"]] == ["2026-11-17", "2026-11-16"]
    assert view["days"][1]["bp"] == pytest.approx(100.0) and view["days"][1]["dollars"] == pytest.approx(100.0)
    assert view["totals"]["days"] == 2 and view["totals"]["mean_bp"] == pytest.approx(50.0)
    assert view["holding"]["side"] == -1
    assert view["backtest"]["protocol_id"] == "qqq-intraday-momentum-20261114-v1"


def test_the_shipped_seed_has_a_full_window():
    data = json.loads(ib.SEED.read_text())["sessions"]
    assert len(data) == ib.LOOKBACK and all(len(s["moves"]) == len(ib.CHECKS) for s in data)
    assert data[-1]["day"] == "2026-11-13"


def test_decide_matches_the_study_rule():
    lv = {"long": 101.0, "short": 99.0}
    assert ib.decide(0, 101.5, lv) == (False, 1)
    assert ib.decide(0, 100.0, lv) == (False, 0)
    assert ib.decide(1, 101.5, lv) == (False, 0)  # held
    assert ib.decide(1, 100.0, lv) == (True, 0)  # stopped, flat
    assert ib.decide(1, 98.0, lv) == (True, -1)  # stopped and reversed
    assert ib.decide(-1, 102.0, lv) == (True, 1)


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("INTRADAY_MOMENTUM_BOOK_ENABLED", raising=False)
    assert not ib.enabled()


def test_the_band_anchors_on_the_real_previous_close_from_the_quote(tmp_path):
    # The book's last recorded close is 100, but the real previous session (an early close it never recorded) closed at
    # 104. Monday opens at 104 and trades at 103.3 by 10:00: with the real close the lower band is 104 x 0.995 = 103.48.
    clock = Clock(at(DAY, 9, 59, 30))
    feed = Feed(clock, base=104.0, path={580: 103.3})
    b = book(tmp_path, clock, feed, quote=quotes(clock, feed=feed, prev=104.0))
    run_until(b, clock, DAY, 10, 1)
    assert [t["side"] for t in b.store.trades()] == [-1]
    # Without a usable previous close the check waits, and is missed after five minutes, never traded on a guess.
    (tmp_path / "noprev").mkdir()
    other = book(tmp_path / "noprev", clock, feed, quote=quotes(clock, feed=feed, prev=0))
    clock.t = at(DAY, 9, 59, 30)
    run_until(other, clock, DAY, 10, 6)
    assert other.store.trades() == [] and other.store.checks()[0]["status"] == "missed"


def test_the_session_record_waits_for_the_1559_bar(tmp_path):
    clock = Clock(at(DAY, 16, 0, 5))
    feed = Feed(clock)
    b = book(tmp_path, clock, feed)
    b._bars = lambda now: [x for x in feed.today_minutes("QQQ", now) if x["time"] < at(DAY, 15, 58)]  # a stale read
    b.run()
    assert not b.store.has_session(DAY)
    b._bars = lambda now: feed.today_minutes("QQQ", now)
    clock.t += 30
    b.run()
    assert b.store.has_session(DAY)
