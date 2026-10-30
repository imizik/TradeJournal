"""Radar's dip-buy candidate rule ``radar-dip-v0``, on invented fixture passes only (no recorded session, no trades)."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta

import pytest

from app.engine import radar_alerts, radar_dip, radar_rules
from app.engine.chart_math import ET
from app.engine.radar_evidence import census
from app.engine.radar_runner import RadarRunner
from app.engine.radar_store import RadarEvent, RadarStore
from app.engine.tradier import TradierQuote
from scripts import radar_outcomes

DAY = "2030-01-15"  # an invented Tuesday
OPEN = datetime(2030, 1, 15, 9, 30, tzinfo=ET)
STOCKS = ["AAA", "BBB", "CCC"]
UNIVERSE = {
    "version": "radar-universe-test",
    "symbols": [{"symbol": "SPY", "kind": "etf", "benchmark": True}]
    + [{"symbol": s, "kind": "stock", "benchmark": False, "sector": None} for s in STOCKS],
    "groups": [],
}
SHARES = 200_000  # a minute, so about $20M a minute at $100: liquid
NO_TREND = {}


def dip_path(gap=98.0, low=97.0, low_at=10, turn=(97.2, 97.3, 97.4, 97.6, 97.8, 98.0, 98.2)):
    """Opens at ``gap``, slides to ``low`` by minute ``low_at``, then climbs through ``turn`` and holds its last."""
    def price(i):
        if i <= low_at:
            return round(gap + (low - gap) * i / low_at, 4)
        return turn[min(i - low_at - 1, len(turn) - 1)]
    return price


def flat(i):
    return 100.0


def _iso(value: datetime) -> str:
    return radar_rules._iso(value.timestamp())


def session(paths: dict, minutes: int = 40, first: int = 0, opens: dict | None = None, shares: int = SHARES):
    """Passes at 09:30 + ``first`` … one a minute; ``paths`` give each symbol's last by minute (default flat 100)."""
    passes, quotes = [], {}
    for i in range(first, first + minutes):
        at = OPEN + timedelta(minutes=i)
        passes.append({"id": i + 1, "session_date": DAY, "started_at": _iso(at), "finished_at": _iso(at + timedelta(seconds=2)),
                       "universe_version": UNIVERSE["version"], "status": "ok"})
        quotes[i + 1] = {}
        for symbol in ["SPY"] + STOCKS:
            price = paths.get(symbol, flat)(i)
            quotes[i + 1][symbol] = {
                "symbol": symbol, "last": price, "prev_close": 100.0, "open": (opens or {}).get(symbol, paths.get(symbol, flat)(0)),
                "high": None, "low": None, "volume": shares * (i + 1), "bid": price, "ask": price,
                "trade_time_ms": int((at + timedelta(seconds=0.5)).timestamp() * 1000), "retrieved_at": _iso(at + timedelta(seconds=1))}
    return passes, quotes


def run(paths, daily=NO_TREND, **kw):
    passes, quotes = session(paths, **kw)
    return radar_dip.replay(UNIVERSE, passes, quotes, daily)


def below_trend(*symbols):
    return {s: {"close": 100.0, "sma": 104.0, "bar_date": "2030-01-14"} for s in symbols}


# ------------------------------------------------------------------ trigger


def test_gap_down_dip_that_reclaims_vwap_fires_once_with_every_field():
    [event] = run({"AAA": dip_path()})
    assert set(event) == set(RadarEvent.__annotations__)
    assert event["event_id"] == "rd0-2030-01-15-dip-aaa-up-1"
    assert (event["kind"], event["direction"], event["rule_version"], event["symbols"]) == ("dip_turn", "up", "radar-dip-v0", ["AAA"])
    # Low at 09:40; 09:45 is the first pass five minutes clear of it and above the sampled VWAP; 09:46 holds it.
    assert event["first_seen_at"] == _iso(OPEN + timedelta(minutes=16, seconds=2))
    assert event["summary"] == ("AAA turning up after a morning dip: low −3.0% at 9:40, now −2.0%, back above its sampled "
                                "VWAP (gapped −2.0%)")
    m = event["measures"]
    assert m["day_change_pct"] == -2.0 and m["low_change_pct"] == -3.0 and m["gap_pct"] == -2.0
    assert m["from_low_pct"] == pytest.approx(1.031, abs=1e-3) and m["low_minutes_ago"] == 6
    assert m["vwap"] == pytest.approx(sum(dip_path()(i) for i in range(17)) / 17, abs=1e-4)  # equal volume a minute
    assert m["spy_day_change_pct"] == 0.0 and "prior_close_vs_average_pct" not in m
    assert [(e["symbol"], e["pass_id"]) for e in event["evidence"]] == [("AAA", 11), ("SPY", 11), ("AAA", 17), ("SPY", 17)]
    assert event["chart"]["symbol"] == "AAA"


def test_below_twenty_day_average_counts_as_weak_without_a_gap():
    path = dip_path(gap=100.0, low=98.0, turn=(98.2, 98.3, 98.4, 98.6, 98.8, 99.0))
    assert run({"BBB": path}) == []  # opened flat and closed above its average: not weak coming in
    [event] = run({"BBB": path}, daily=below_trend("BBB"))
    assert event["summary"].endswith("(closed below its 20-day average)")
    assert event["measures"]["prior_close_vs_average_pct"] == pytest.approx(-3.846, abs=1e-3)


# ------------------------------------------------------------------ no trigger


@pytest.mark.parametrize("path,why", [
    (lambda i: round(98 - 0.1 * i, 4), "still falling: every pass is a new low"),
    (dip_path(low=98.8, gap=99.5), "a dip of 1.2% is under the 1.5% floor (and a 0.5% gap is under 1%)"),
    (dip_path(turn=(97.1, 97.15, 97.2, 97.25, 97.3, 97.35, 97.4)), "a bounce that stays under the sampled VWAP"),
])
def test_no_turn_no_event(path, why):
    assert run({"AAA": path}) == [], why


def test_an_equal_low_only_delays_the_event():
    [event] = run({"AAA": dip_path(turn=(97.2, 97.3, 97.0) + (97.6, 97.8, 98.0, 98.2, 98.4, 98.6))})
    assert event["measures"]["low_minutes_ago"] == 6 and event["first_seen_at"] == _iso(OPEN + timedelta(minutes=19, seconds=2))


def test_thin_or_cheap_names_are_skipped():
    assert run({"AAA": dip_path()}, shares=2_000) == []  # about $0.2M a minute: under $10M all hour
    cheap = [round(p / 25, 4) for p in (97.2, 97.3, 97.4, 97.6, 97.8, 98.0, 98.2)]
    passes, quotes = session({"AAA": dip_path(gap=3.92, low=3.88, turn=cheap)})
    for q in (q for rows in quotes.values() for q in rows.values() if q["symbol"] == "AAA"):
        q["prev_close"] = 4.0
    assert radar_dip.replay(UNIVERSE, passes, quotes, NO_TREND) == []  # under $5


def test_only_the_first_hour():
    late = dip_path(low_at=56)  # low at 10:26, so five clear minutes only come at 10:31
    assert run({"AAA": late}, minutes=70) == []
    passes, _ = session({}, minutes=70)
    assert radar_dip.needed_pass_ids(passes, 60) == set()  # from 10:30 on the rule reads nothing
    assert radar_dip.needed_pass_ids(passes, 59) == {p["id"] for p in passes[:60]}  # 10:29 reads the session so far


def test_a_late_first_pass_sees_no_morning():
    assert run({"AAA": dip_path()}, first=3) == []  # recording started 09:33: the low and VWAP before it are unseen


def test_one_per_stock_and_a_session_cap():
    events = run({s: dip_path() for s in STOCKS})
    assert [e["symbols"][0] for e in events] == STOCKS
    passes, quotes = session({s: dip_path() for s in STOCKS})
    capped = radar_dip.replay(UNIVERSE, passes, quotes, NO_TREND, replace(radar_dip.V0, max_events=2))
    assert [e["symbols"][0] for e in capped] == ["AAA", "BBB"]


# ------------------------------------------------------------------ causality


def test_no_future_pass_is_read():
    passes, quotes = session({"AAA": dip_path()}, minutes=40)
    [event] = radar_dip.replay(UNIVERSE, passes, quotes, NO_TREND)
    fired = next(i for i, p in enumerate(passes) if p["finished_at"] == event["first_seen_at"])
    # Wreck every later pass: the event, built at its own pass, is byte-identical and nothing fires earlier.
    for p in passes[fired + 1:]:
        for q in quotes[p["id"]].values():
            q["last"], q["volume"] = 1.0, 1
    assert radar_dip.replay(UNIVERSE, passes, quotes, NO_TREND) == [event]
    assert radar_dip.replay(UNIVERSE, passes[:fired + 1], quotes, NO_TREND) == [event]
    assert radar_dip.replay(UNIVERSE, passes[:fired], quotes, NO_TREND) == []
    assert max(radar_dip.needed_pass_ids(passes, fired)) == passes[fired]["id"]


def test_daily_context_reads_only_closes_before_the_session():
    def bar(day, close):
        return {"t": f"{day}T05:00:00Z", "c": close}
    days = [(datetime(2029, 12, 10) + timedelta(days=n)).date() for n in range(40)]
    weekdays = [d for d in days if d.weekday() < 5 and d.isoformat() < DAY][-20:]
    rows = [bar(d.isoformat(), 100.0 + n) for n, d in enumerate(weekdays)]
    later = [bar(DAY, 1.0), bar("2030-01-16", 1.0)]  # the session's own bar and a later one are never read
    ctx = radar_dip.daily_context({"AAA": rows + later, "BBB": rows[1:]}, DAY)
    assert ctx == {"AAA": {"close": 119.0, "sma": 109.5, "bar_date": weekdays[-1].isoformat()}}  # BBB: 19 closes
    assert radar_dip.daily_context({"AAA": rows}, "2030-01-25") == {}  # newest close 10 days old


# ------------------------------------------------------------------ recorder, receipts and scoring


class Quotes:
    """The recorder's quote call, priced from the fixture paths at the runner's clock minute."""
    def __init__(self, clock, paths):
        self.clock, self.paths = clock, paths

    def __call__(self, symbols):
        now = self.clock()
        i = int((now - OPEN.timestamp()) // 60)
        out = {}
        for s in symbols:
            price = self.paths.get(s, flat)(i)
            out[s] = TradierQuote(symbol=s, last=price, bid=price, ask=price, volume=SHARES * (i + 1),
                                  trade_date=int((now - 1) * 1000),
                                  raw={"prevclose": "100", "open": str(self.paths.get(s, flat)(0)), "high": None, "low": None})
        return out


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


class Clock:
    def __init__(self):
        self.now = OPEN.timestamp() + 5

    def __call__(self):
        return self.now


class Alerts:
    def __init__(self):
        self.recorded = []

    def record(self, events):
        self.recorded += [e["event_id"] for e in events]

    def deliver(self):
        pass


def _record(tmp_path, minutes, dip=radar_dip.V0, dip_alerts=False):
    clock = Clock()
    store = RadarStore(tmp_path / "radar.sqlite")
    runner = RadarRunner(store, Calendar(), universe=UNIVERSE, quotes=Quotes(clock, {"AAA": dip_path()}), clock=clock,
                         news=lambda *a, **k: [], dip=dip, dip_alerts=dip_alerts, alerts=Alerts(),
                         daily=lambda symbols, day: {})
    for _ in range(minutes):
        runner.run_once()
        clock.now += 60
    return runner, store


def test_recorder_writes_dip_events_under_their_own_receipt_and_leaves_the_trial_alone(tmp_path):
    runner, store = _record(tmp_path, 95)
    _, plain = _record(tmp_path / "off", 95, dip=None)
    [event] = [e for e in store.events(DAY) if radar_dip.is_dip(e)]
    assert event["event_id"] == "rd0-2030-01-15-dip-aaa-up-1" and runner.alerts.recorded == []  # record mode: no ping
    receipts, configs = store.detection_evidence()
    off_receipts, off_configs = plain.detection_evidence()
    # The trial rules' receipt fields and frozen config are exactly what they are with the dip rule off.
    trial = {k: v for k, v in receipts[1].items() if k != "dip"}
    assert {k: v for k, v in trial.items() if k != "recorded_at"} == {k: v for k, v in off_receipts[1].items() if k != "recorded_at"}
    assert set(off_configs) < set(configs)
    assert configs[receipts[1]["dip"]["config_digest"]]["rules"] == asdict(radar_dip.V0)
    claimed = [i for r in receipts.values() for i in r["dip"]["event_ids"]]
    assert claimed == [event["event_id"]] and all(event["event_id"] not in r["event_ids"] for r in receipts.values())
    # The trial's census is unchanged; the dip rule has its own.
    today = "2030-01-16"
    [trial_row], [off_row] = census(store, today), census(plain, today)
    assert {k: v for k, v in trial_row.items()} == {**off_row}
    [dip_row] = census(store, today, side="dip")
    assert dip_row["rule_version"] == "radar-dip-v0" and dip_row["events"] == 1
    assert census(plain, today, side="dip") == []
    [scored] = [r for r in radar_outcomes.score_store(store, None, set(), today) if r["rule_version"] == "radar-dip-v0"]
    assert set(scored["horizons"]) == {"30m", "60m", "close"} and scored["excluded"] == {}


def test_recorder_census_flags_a_dip_session_with_a_failed_pass(tmp_path):
    def daily(symbols, day):
        raise RuntimeError("no daily bars")
    clock = Clock()
    store = RadarStore(tmp_path / "radar.sqlite")
    runner = RadarRunner(store, Calendar(), universe=UNIVERSE, quotes=Quotes(clock, {}), clock=clock,
                         news=lambda *a, **k: [], dip=radar_dip.V0, daily=daily)
    for _ in range(3):
        runner.run_once()
        clock.now += 60
    receipts, _ = store.detection_evidence()
    assert {r["status"] for r in receipts.values()} == {"ok"} and {r["dip"]["status"] for r in receipts.values()} == {"failed"}


def test_alert_mode_hands_dip_events_to_the_phone(tmp_path):
    runner, _ = _record(tmp_path, 20, dip_alerts=True)
    assert runner.alerts.recorded == ["rd0-2030-01-15-dip-aaa-up-1"]
    [event] = runner.store.events(DAY)
    title, body = radar_alerts.message(event)
    assert title == "Radar dip: AAA turning up, −2.0% (low −3.0%)"
    assert body.startswith("AAA turning up after a morning dip") and body.endswith("9:46 AM ET")


@pytest.mark.parametrize("value,mode", [("", "off"), ("record", "record"), ("ALERT", "alert"), ("on", "off")])
def test_mode_from_env(monkeypatch, value, mode):
    monkeypatch.setenv("RADAR_DIP_RULES", value)
    assert radar_dip.mode_from_env() == mode


def test_daily_fetch_uses_the_no_retry_read_and_fails_fast(monkeypatch):
    from app.engine import alpaca
    weekdays = [d for d in ((datetime(2029, 12, 10) + timedelta(days=n)).date() for n in range(40))
                if d.weekday() < 5 and d.isoformat() < DAY][-20:]
    rows = [{"t": f"{d.isoformat()}T05:00:00Z", "c": 100.0} for d in weekdays]
    calls = []

    def fast(path, params):
        calls.append(params.get("page_token"))
        if params.get("page_token") is None:
            return {"bars": {"AAA": rows[:10]}, "next_page_token": "p2"}
        return {"bars": {"AAA": rows[10:]}, "next_page_token": None}

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", fast)
    monkeypatch.setattr(alpaca, "_alpaca_get", lambda *a: pytest.fail("the retrying read sleeps on a 429"))
    assert radar_dip.fetch_daily(["AAA"], DAY)["AAA"]["sma"] == 100.0 and calls == [None, "p2"]

    def limited(path, params):
        raise alpaca.AlpacaFastFailure("Alpaca rate limited.")
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", limited)
    with pytest.raises(alpaca.AlpacaFastFailure):
        radar_dip.fetch_daily(["AAA"], DAY)
