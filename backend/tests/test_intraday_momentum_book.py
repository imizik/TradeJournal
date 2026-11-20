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


class Backup:
    """Alpaca's reads, by default with nothing to give; ``calls`` counts every ask."""

    def __init__(self, clock: Clock, bars: Feed | None = None, spread: float = 0.04, age: float = 1.0,
                 prev: tuple[str, float] | None = None, sip: Feed | None = None):
        self.clock, self.bars, self.spread, self.age, self.prev, self.sip = clock, bars, spread, age, prev, sip
        self.calls: list[str] = []

    def quote(self, symbol):
        self.calls.append("quote")
        if self.bars is None:
            return None
        last = self.bars.today_minutes(symbol, self.clock.t)[-1]["close"]
        ms = int((self.clock.t - self.age) * 1000)
        return TradierQuote(symbol=symbol, bid=round(last - self.spread / 2, 2), ask=round(last + self.spread / 2, 2),
                            bid_date=ms, ask_date=ms)

    def minutes(self, symbol, day, now, feed):
        self.calls.append(f"minutes:{feed}")
        source = self.sip if feed == "sip" else self.bars
        return None if source is None else source.today_minutes(symbol, now)

    def previous_close(self, symbol, day):
        self.calls.append("previous_close")
        return None if self.prev is None else (date.fromisoformat(self.prev[0]), self.prev[1])


def book(tmp_path, clock, feed, quote=None, calendar=None, seed_path=None, backup=None):
    store = ib.Store(tmp_path / "book.sqlite3", seed=seed_path or seed(tmp_path))
    return ib.IntradayMomentumBook(calendar or Calendar(), feed, clock=clock, quote=quote or quotes(clock, feed=feed),
                                   backup=backup or Backup(clock), store=store)


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


def test_today_view_steps_the_band_by_check_and_projects_the_hours_ahead(tmp_path, monkeypatch):
    # sigma grows by the hour (0.2% at 10:00 .. 0.7% at 15:00); open 100.4 against a previous close of 100: the upper band
    # anchors on 100.4, the lower on 100.
    path = tmp_path / "seed.json"
    moves = {str(m): 0.002 + 0.001 * i for i, m in enumerate(ib.CHECKS)}
    path.write_text(json.dumps({"sessions": [{"day": f"2026-09-{k + 1:02d}" if k < 30 else f"2026-10-{k - 29:02d}", "open": 100.0,
                                              "close": 100.0, "moves": moves} for k in range(ib.LOOKBACK)]}))
    clock = Clock(at(DAY, 9, 59, 30))
    feed = Feed(clock, base=100.4, path={590: 101.2})
    b = book(tmp_path, clock, feed, seed_path=path)
    run_until(b, clock, DAY, 11, 30)
    assert ib.today_view(b.store, clock.t, False) is None  # the book is off: nothing to draw
    view = ib.today_view(b.store, clock.t, True)
    assert view["day"] == DAY and view["until"] == at(DAY, 16, 0)
    assert [(c["minute"], c["at"], c["status"]) for c in view["checks"]] == [(600, at(DAY, 10, 0), "done"), (660, at(DAY, 11, 0), "done")]
    assert view["checks"][0]["upper"] == pytest.approx(100.4 * (1 + 1.25 * 0.002))
    assert view["checks"][0]["lower"] == pytest.approx(100.0 * (1 - 1.25 * 0.002))
    assert view["checks"][1]["upper"] == pytest.approx(100.4 * (1 + 1.25 * 0.003))
    assert [a["minute"] for a in view["ahead"]] == [720, 780, 840, 900]
    for a, s in zip(view["ahead"], (0.004, 0.005, 0.006, 0.007)):
        assert a["upper"] == pytest.approx(100.4 * (1 + 1.25 * s)) and a["lower"] == pytest.approx(100.0 * (1 - 1.25 * s))
    [t] = view["trades"]
    assert (t["side"], t["exit"], t["bp"]) == (1, None, None) and t["entry_at"] == pytest.approx(at(DAY, 10, 0), abs=60)
    run_until(b, clock, DAY, 16, 1)
    view = ib.today_view(b.store, at(DAY, 16, 5), True)
    assert view["ahead"] == [] and len(view["checks"]) == 6
    [t] = view["trades"]
    # 15:00: the band (101.28) passes the price (101.2): stopped; a long's bp on the day's open.
    assert t["how"] == "stop" and t["bp"] == pytest.approx(round((t["exit"] - t["entry"]) / 100.4 * 1e4, 2))
    # A check whose time has passed but is not recorded yet ends the band drawn before it (none drawn on as if checked).
    pending = ib.Store(tmp_path / "pending.sqlite3", seed=path)
    pending.add_check(DAY, 600, "done", price=101.0, upper=100.65, lower=99.75, vwap=100.5)
    view = ib.today_view(pending, at(DAY, 11, 2), True)
    assert view["until"] == at(DAY, 11, 0) and [a["minute"] for a in view["ahead"]] == [720, 780, 840, 900]
    # The next day, before its first check: nothing, never yesterday's lines.
    assert ib.today_view(b.store, at("2026-11-17", 9, 45), True) is None


def test_read_carries_today_only_while_the_book_is_on(tmp_path, monkeypatch):
    path = tmp_path / "book.sqlite3"
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_PATH", str(path))
    assert ib.read(at(DAY, 11, 0))["today"] is None  # no file
    ib.Store(path, seed=None).add_check(DAY, 600, "done", price=101.0, upper=100.5, lower=99.5, vwap=100.2)
    assert ib.read(at(DAY, 11, 0))["today"] is None  # off
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_ENABLED", "true")
    today = ib.read(at(DAY, 11, 0))["today"]
    assert today["checks"][0]["upper"] == 100.5 and today["ahead"] == []  # no window in this store: nothing projected


# ------------------------------------------------------------------ the Alpaca backup


class DownFeed:
    def today_minutes(self, symbol, now):
        raise RuntimeError("Tradier timesales failed")


def tradier_down(symbols):
    raise RuntimeError("Tradier is down")


def test_tradier_down_trades_from_alpaca_bars_close_and_quote_and_says_so(tmp_path, monkeypatch):
    clock = Clock(at(DAY, 10, 0, 5))
    alpaca = Feed(clock, path={580: 101.0})
    backup = Backup(clock, bars=alpaca, prev=(PREV, 100.0))
    b = book(tmp_path, clock, DownFeed(), quote=tradier_down, backup=backup)
    b.run()
    (t,) = b.store.trades()
    assert (t["side"], t["entry"], t["entry_source"]) == (1, 101.02, "alpaca_iex")
    (c,) = b.store.checks()
    assert (c["status"], c["source"]) == ("done", "alpaca")
    b.feed, b.quote = Feed(clock, path={580: 101.0}), quotes(clock, feed=alpaca)  # Tradier is back by the close
    clock.t = at(DAY, 15, 59, 5)
    b.run()
    t = b.store.trades()[0]
    assert (t["how"], t["exit"], t["exit_source"]) == ("close", 100.99, "tradier")
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_ENABLED", "true")
    row = ib.summary(b.store.trades(), b.store.checks(), at("2026-11-17", 12, 0), True)["days"][0]
    assert row["backup"] is True and row["trades"][0]["entry_source"] == "alpaca_iex"


def test_tradier_fine_never_asks_alpaca_all_day(tmp_path):
    clock = Clock(at(DAY, 9, 59, 30))
    feed = Feed(clock, path={580: 101.0})
    backup = Backup(clock, bars=feed, prev=(PREV, 100.0), sip=feed)
    b = book(tmp_path, clock, feed, backup=backup)
    run_until(b, clock, DAY, 16, 30)
    assert backup.calls == []
    assert len(b.store.trades()) == 1 and b.store.has_session(DAY)
    assert {c["source"] for c in b.store.checks()} == {"tradier"}
    assert ib.summary(b.store.trades(), b.store.checks(), at("2026-11-17", 12, 0), True)["days"][0]["backup"] is False


def test_tradier_bars_a_few_seconds_behind_do_not_ask_alpaca(tmp_path):
    clock = Clock(at(DAY, 10, 0, 5))
    feed = Feed(clock, path={580: 101.0})
    backup = Backup(clock, bars=feed, prev=(PREV, 100.0))
    b = book(tmp_path, clock, feed, backup=backup)
    b._bars = lambda now: [x for x in feed.today_minutes("QQQ", now) if x["time"] < at(DAY, 9, 58)]  # the 09:59 bar lags
    b.run()
    assert backup.calls == [] and b.store.checks() == []
    clock.t = at(DAY, 10, 2, 5)  # still short two minutes after the check: Alpaca's bars decide
    b.run()
    assert backup.calls[0] == "minutes:iex" and b.store.checks()[0]["source"] == "alpaca"


def test_a_stale_alpaca_quote_trades_nothing_and_the_check_is_missed_as_before(tmp_path):
    clock = Clock(at(DAY, 10, 0, 5))
    alpaca = Feed(clock, path={580: 101.0})
    b = book(tmp_path, clock, DownFeed(), quote=tradier_down, backup=Backup(clock, bars=alpaca, prev=(PREV, 100.0), age=61))
    run_until(b, clock, DAY, 10, 6)
    assert b.store.trades() == []
    (c,) = b.store.checks()
    assert (c["status"], c["source"]) == ("missed", None)


def test_an_alpaca_close_from_an_older_session_is_not_the_previous_close(tmp_path):
    clock = Clock(at(DAY, 10, 0, 5))
    alpaca = Feed(clock, path={580: 101.0})
    stale = Backup(clock, bars=alpaca, prev=("2026-11-12", 100.0))  # Thursday's close, but Friday was a session
    b = book(tmp_path, clock, DownFeed(), quote=tradier_down, backup=stale)
    b.run()
    assert b.store.checks() == [] and b.store.trades() == []


def test_a_session_tradier_cannot_give_is_recorded_from_alpaca_sip_after_its_delay(tmp_path):
    clock = Clock(at(DAY, 16, 0, 30))
    sip = Feed(clock)
    backup = Backup(clock, sip=sip)
    b = book(tmp_path, clock, DownFeed(), quote=tradier_down, backup=backup)
    b.run()
    assert not b.store.has_session(DAY) and backup.calls == []  # SIP is still inside its 15-minute delay
    clock.t = at(DAY, 16, 16, 30)
    b.run()
    assert b.store.has_session(DAY) and backup.calls == ["minutes:sip"]
    import sqlite3

    with sqlite3.connect(b.store.path) as db:
        assert db.execute("SELECT source FROM session WHERE day = ?", (DAY,)).fetchone()[0] == "alpaca_sip"


def test_rows_from_before_the_backup_read_as_tradier(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(ib.SCHEMA)  # the tables as #826 shipped them, no source columns
    db.execute("INSERT INTO session VALUES ('2026-11-13', 100, 100, '{}')")
    db.execute("INSERT INTO check_row VALUES ('2026-11-16', 600, 'done', 101, 100.5, 99.5, 100.4, NULL)")
    db.execute("INSERT INTO check_row VALUES ('2026-11-16', 660, 'missed', NULL, NULL, NULL, NULL, 'late')")
    db.execute("INSERT INTO trade (day, side, day_open, entry_at, entry, exit_at, exit, how, status) "
               "VALUES ('2026-11-16', 1, 100, 1, 101.01, 2, 101.2, 'close', 'closed')")
    db.commit()
    db.close()
    store = ib.Store(path, seed=None)
    (t,) = store.trades()
    assert (t["entry_source"], t["exit_source"]) == ("tradier", "tradier")
    assert [c["source"] for c in store.checks()] == ["tradier", None]
    row = ib.summary(store.trades(), store.checks(), at("2026-11-17", 12, 0), True)["days"][0]
    assert row["backup"] is False
    store.add_session("2026-11-16", 100, 101, {}, "alpaca_sip")  # the upgraded file takes new rows
    store.add_check("2026-11-17", 600, "done", price=1, source="alpaca")
    assert store.checks_on("2026-11-17")[0]["source"] == "alpaca"


def test_two_openers_upgrading_an_old_file_at_once_both_succeed(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor

    for k in range(20):
        path = tmp_path / f"old{k}.sqlite3"
        with sqlite3.connect(path) as db:
            db.executescript(ib.SCHEMA)  # as #826 shipped it
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda _: ib.Store(path, seed=None), range(4)))  # none raises
