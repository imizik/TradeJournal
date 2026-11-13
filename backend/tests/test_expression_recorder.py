"""Expression recorder: choosing alternatives, scoring them by hand, and the pass on invented fills and quotes."""

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import expression_recorder as er
from app.engine import reconstructor
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor
from app.engine.options_models import OptionChain, OptionContract
from app.engine.tradier import TradierQuote
from app.models import Account, Fill
from app.routers.fills import _rebuild_trades
from scripts import expression_scorecard

EXP = date(2026, 10, 23)
LATER = date(2026, 11, 20)
WED = date(2026, 10, 21)
ROTH, WEBULL = UUID(int=1), UUID(int=3)


def contract(kind, strike, delta, bid=1.0, ask=1.1, expiration=EXP, root="AAA"):
    return OptionContract(symbol=f"{root}{expiration:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}", underlying="AAA", root=root,
                          expiration=expiration, option_type=kind, strike=strike, multiplier=100, bid=bid, ask=ask, last=None,
                          bid_size=1, ask_size=1, volume=1, open_interest=1, bid_time=None, ask_time=None, trade_time=None, iv=None,
                          iv_smoothed=None, delta=delta, gamma=None, theta=None, vega=None, greeks_updated_at=None)


CALLS = {90: 0.78, 95: 0.66, 100: 0.5, 105: 0.33, 110: 0.2}
PUTS = {90: -0.22, 95: -0.34, 100: -0.5, 105: -0.67, 110: -0.8}


def chain(expiration=EXP):
    contracts = [contract("call", k, d, *((3.0, 3.2) if k == 100 else (1.0, 1.1)), expiration=expiration) for k, d in CALLS.items()]
    contracts += [contract("put", k, d, *((2.8, 3.0) if k == 100 else (1.0, 1.1)), expiration=expiration) for k, d in PUTS.items()]
    return OptionChain(underlying="AAA", expiration=expiration, provider="test", fetched_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
                       contracts=tuple(contracts))


def far():
    contracts = (contract("call", 98, 0.6, expiration=LATER), contract("call", 102, 0.45, expiration=LATER),
                 contract("put", 98, -0.4, expiration=LATER))
    return OptionChain(underlying="AAA", expiration=LATER, provider="test", fetched_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
                       contracts=contracts)


def strikes(legs):
    return {alt: [(leg["symbol"][-8:], leg["sign"]) for leg in parts] for alt, parts in legs.items()}


def by(kind, strike, chained=None):
    return next(c for c in (chained or chain()).contracts if c.option_type == kind and c.strike == strike)


def test_alternatives_for_a_call():
    legs = er.choose(by("call", 100), chain(), far(), 100.0, "AAA")
    assert strikes(legs) == {"as_traded": [("00100000", 1)], "deeper": [("00095000", 1)],
                             "spread": [("00100000", 1), ("00105000", -1)],  # straddle 6.0: 106 nearest 105
                             "later": [("00098000", 1)], "shares": [("AAA", 1)]}
    assert legs["shares"][0]["kind"] == "share" and legs["as_traded"][0]["multiplier"] == 100


def test_alternatives_for_a_put_and_what_is_left_out():
    legs = er.choose(by("put", 100), chain(), None, 100.0, None)
    assert strikes(legs) == {"as_traded": [("00100000", 1)], "deeper": [("00105000", 1)],
                             "spread": [("00100000", 1), ("00095000", -1)]}
    assert er.choose(by("put", 100), chain(), None, 100.0, "AAA")["shares"][0]["sign"] == -1  # short shares for a put
    assert "deeper" not in er.choose(by("call", 95), chain(), None, None, None)  # already 0.66
    assert "spread" not in er.choose(by("call", 100), chain(), None, None, None)  # no price, no straddle


def test_the_later_expiration_is_three_weeks_out_and_after_his():
    listed = [date(2026, 10, 23), date(2026, 11, 6), date(2026, 11, 13), date(2026, 11, 20)]
    assert er.later_expiration(listed, EXP, WED) == date(2026, 11, 13)
    assert er.later_expiration(listed, date(2026, 11, 13), WED) == date(2026, 11, 20)
    assert er.later_expiration(listed[:2], EXP, WED) is None


A, B = "AAA261023C00100000", "AAA261023C00105000"
LEGS = {"as_traded": [{"symbol": A, "kind": "option", "sign": 1, "multiplier": 100}],
        "spread": [{"symbol": A, "kind": "option", "sign": 1, "multiplier": 100}, {"symbol": B, "kind": "option", "sign": -1, "multiplier": 100}],
        "shares": [{"symbol": "AAA", "kind": "share", "sign": 1, "multiplier": 1}]}


def snap(role, when, contracts, price, quotes, quoted_at=None, status="recorded"):
    stamp = datetime.fromisoformat(when).replace(tzinfo=ET).timestamp()
    return {"role": role, "executed_at": when, "contracts": contracts, "price": price, "status": status, "quotes": quotes,
            "quoted_at": quoted_at if quoted_at is not None else stamp + 20}


def q(a, b, stock, delta_a=0.5, delta_b=0.25):
    return {A: {"bid": a[0], "ask": a[1], "delta": delta_a}, B: {"bid": b[0], "ask": b[1], "delta": delta_b},
            "AAA": {"bid": stock[0], "ask": stock[1], "delta": None}}


SNAPS = [snap("entry", "2026-10-21T10:00:00", 2, 300, q((2.9, 3.0), (1.0, 1.1), (99.99, 100.01))),
         snap("exit", "2026-10-21T11:00:00", 1, 400, q((3.9, 4.0), (1.5, 1.6), (102.0, 102.02))),
         snap("expiry", "2026-10-23T15:58:00", 1, 0, q((0.0, 0.05), (0.0, 0.05), (98.0, 98.02)))]


def test_score_sizes_by_delta_and_closes_proportionally():
    out = er.score({"key": "k", "ticker": "AAA", "option_type": "call", "legs": LEGS}, SNAPS)
    # as traded: 2 x 100 x 3.00 paid; 1 sold at 3.90; 1 worth 0 at expiry.
    # shares: 2 contracts x 50 delta = 100 shares at 100.01; 50 sold at 102, 50 at 98.
    # spread: 25 delta per spread, so 4: 400 x 3.00 - 400 x 1.00 = 800 paid; 2 closed for 200 x 3.90 - 200 x 1.60; 2 for 0 - 200 x 0.05.
    assert out["pnl"] == {"as_traded": -210.0, "spread": -350.0, "shares": -1.0}
    assert out["actual"] == -200.0 and out["premium"] == 600.0
    assert out["complete"] and not out["late"] and out["held"] == "past the entry session"


def test_score_drops_what_it_cannot_price_and_flags_gaps():
    missing = [dict(SNAPS[0], quotes={**SNAPS[0]["quotes"], B: {"bid": None, "ask": None, "delta": 0.25}}), *SNAPS[1:]]
    assert set(er.score({"key": "k", "ticker": "AAA", "option_type": "call", "legs": LEGS}, missing)["pnl"]) == {"as_traded", "shares"}
    gap = er.score({"key": "k", "ticker": "AAA", "option_type": "call", "legs": LEGS}, [SNAPS[0], dict(SNAPS[1], status="unavailable")])
    assert not gap["complete"] and gap["problem"] == "a exit snapshot is unavailable"
    late = er.score({"key": "k", "ticker": "AAA", "option_type": "call", "legs": LEGS}, [dict(SNAPS[0], quoted_at=SNAPS[0]["quoted_at"] + 600),
                                                                                      *SNAPS[1:]])
    assert late["late"] and late["complete"]
    still_open = er.score({"key": "k", "ticker": "AAA", "option_type": "call", "legs": LEGS}, SNAPS[:2])
    assert not still_open["complete"]


# ------------------------------------------------------------------ the pass


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", type("Wed", (date,), {"today": classmethod(lambda cls: WED)}))
    monkeypatch.delenv("EXPRESSION_RECORDER_ENABLED", raising=False)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


n = iter(range(100, 10_000))


def fill(engine, hhmm, side="buy_to_open", qty=1, price=300, account=ROTH, strike=100, day=WED):
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=next(n)), account_id=account, ticker="AAA", instrument_type="option", side=side, contracts=qty,
                    price=price, executed_at=datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time()),
                    raw_email_id=f"gmail:{next(n)}", option_type="call", strike=strike, expiration=EXP))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


class Chains:
    def __init__(self):
        self.calls = []
        self.fail = False

    def chain(self, symbol, expiration, timeout=None):
        self.calls.append(("chain", symbol, expiration))
        if self.fail:
            raise RuntimeError("rate limited")
        return chain() if expiration == EXP else far()

    def expirations(self, symbol, timeout=None):
        return [EXP, LATER]


def quote(symbols, greeks=False):
    out = {}
    for s in symbols:
        if s == "AAA":
            out[s] = TradierQuote(symbol=s, bid=99.99, ask=100.01, mid=100.0, last=100.0)
        else:
            c = next((c for c in chain().contracts + far().contracts if c.symbol == s), None)
            if c is not None:
                out[s] = TradierQuote(symbol=s, bid=c.bid, ask=c.ask, delta=c.delta)
    return out


def clock_at(hhmm, day=WED):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def recorder(engine, tmp_path, clock, chains, calendar=None):
    return er.ExpressionRecorder(engine, calendar, clock=clock, chains=chains, quote=quote, store=er.Store(tmp_path / "x.sqlite3"))


def test_the_pass_records_entries_exits_and_expiry(engine, tmp_path):
    clock, chains = Clock(clock_at("09:59")), Chains()
    rec = recorder(engine, tmp_path, clock, chains)
    fill(engine, "10:00")
    fill(engine, "10:00", account=WEBULL)  # Webull is dormant: never quoted
    clock.now = clock_at("10:01")
    rec.run()
    positions = rec.store.positions()
    assert len(positions) == 1 and set(positions[0]["legs"]) == {"as_traded", "deeper", "spread", "later", "shares"}
    fill(engine, "10:30", side="sell_to_close", price=310)
    clock.now = clock_at("10:31")
    rec.run()
    rec.run()  # throttled: nothing twice
    snaps = rec.store.snapshots(positions[0]["key"])
    assert sorted(s["role"] for s in snaps) == ["entry", "exit"] and all(s["status"] == "recorded" for s in snaps)
    assert not er.score(positions[0], snaps)["complete"]  # counted only once the expiry-day check has run
    clock.now = clock_at("15:58", EXP)
    rec.run()
    snaps = rec.store.snapshots(positions[0]["key"])
    assert next(s for s in snaps if s["role"] == "expiry")["note"] == "closed before expiry; every fill quoted"
    result = er.score(positions[0], snaps)
    # Unchanged quotes: his contract bought at the 3.20 ask and sold at the 3.00 bid.
    assert result["complete"] and result["actual"] == 10.0 and result["pnl"]["as_traded"] == pytest.approx(-20.0)


def test_an_open_position_is_closed_at_expiry_and_scored(engine, tmp_path):
    clock = Clock(clock_at("09:59"))
    rec = recorder(engine, tmp_path, clock, Chains())
    fill(engine, "10:00", qty=2)
    clock.now = clock_at("10:01")
    rec.run()
    clock.now = clock_at("15:58", EXP)
    rec.run()
    rec._last_run = 0
    rec.run()  # once only
    key = rec.store.positions()[0]["key"]
    snaps = rec.store.snapshots(key)
    assert [s["role"] for s in sorted(snaps, key=lambda s: s["executed_at"])] == ["entry", "expiry"]
    card = expression_scorecard.scorecard(rec.store)
    assert card["counted"] == 1 and card["past the entry session"]["positions"] == 1
    assert card["all"]["shares"]["positions"] == 1


def test_a_position_opened_before_the_recorder_and_failures(engine, tmp_path):
    clock, chains = Clock(clock_at("09:59")), Chains()
    fill(engine, "09:40")  # before the recorder started: never seen
    rec = recorder(engine, tmp_path, clock, chains)
    fill(engine, "10:00")  # an add to that position
    clock.now = clock_at("10:01")
    rec.run()
    assert rec.store.positions() == []
    fill(engine, "10:05", strike=105)
    chains.fail = True
    clock.now = clock_at("10:06")
    rec.run()
    rec._last_run = 0
    rec.run()  # inside RETRY_SECONDS: no second request
    assert len([c for c in chains.calls if c[0] == "chain"]) == 1
    clock.now = clock_at("10:16")
    rec._last_run = 0
    rec.run()  # past GIVE_UP_SECONDS: recorded as skipped, never asked again
    assert rec.store.seen([k for k in _keys(rec)]) and rec.store.positions() == []


def _keys(rec):
    import sqlite3
    with sqlite3.connect(rec.store.path) as db:
        return [r[0] for r in db.execute("SELECT fill_key FROM snapshot WHERE status = 'skipped'")]


def test_nothing_runs_outside_the_session(engine, tmp_path):
    clock, chains = Clock(clock_at("09:59")), Chains()
    rec = recorder(engine, tmp_path, clock, chains)
    fill(engine, "10:00")
    clock.now = clock_at("17:00")
    rec.run()
    assert chains.calls == []


def test_the_monitor_builds_it_only_when_switched_on(engine, tmp_path, monkeypatch):
    assert LevelAlertMonitor(engine).expressions is None
    monkeypatch.setenv("EXPRESSION_RECORDER_ENABLED", "true")
    monkeypatch.setenv("EXPRESSION_RECORDER_PATH", str(tmp_path / "on.sqlite3"))
    assert isinstance(LevelAlertMonitor(engine).expressions, er.ExpressionRecorder)
    assert (tmp_path / "on.sqlite3").exists()


P = "AAA261023P00100000"


def test_a_put_holds_short_shares():
    legs = {"as_traded": [{"symbol": P, "kind": "option", "sign": 1, "multiplier": 100}],
            "shares": [{"symbol": "AAA", "kind": "share", "sign": -1, "multiplier": 1}]}
    snaps = [snap("entry", "2026-10-21T10:00:00", 1, 200, {P: {"bid": 1.9, "ask": 2.0, "delta": -0.5},
                                                          "AAA": {"bid": 99.99, "ask": 100.01, "delta": None}}),
             snap("exit", "2026-10-21T11:00:00", 1, 290, {P: {"bid": 2.9, "ask": 3.0, "delta": -0.6},
                                                         "AAA": {"bid": 98.0, "ask": 98.02, "delta": None}})]
    out = er.score({"key": "k", "ticker": "AAA", "option_type": "put", "legs": legs}, snaps)
    # 50 shares sold short at the 99.99 bid, bought back at the 98.02 ask.
    assert out["pnl"] == {"as_traded": 90.0, "shares": 98.5}


def test_an_exit_after_the_expiry_close_comes_first():
    snaps = [SNAPS[0], dict(SNAPS[2], contracts=None, executed_at="2026-10-23T15:58:00"),
             snap("exit", "2026-10-23T15:59:00", 2, 50, q((0.4, 0.5), (0.0, 0.05), (101.0, 101.02)))]
    out = er.score({"key": "k", "ticker": "AAA", "option_type": "call", "legs": LEGS}, snaps)
    assert out["complete"] and out["actual"] == -500.0 and out["pnl"]["as_traded"] == -520.0


def test_a_missed_exit_makes_the_position_incomplete(engine, tmp_path):
    clock = Clock(clock_at("09:59"))
    rec = recorder(engine, tmp_path, clock, Chains())
    fill(engine, "10:00", qty=2)
    clock.now = clock_at("10:01")
    rec.run()
    fill(engine, "11:00", side="sell_to_close", qty=1, price=350)  # its email is never seen in time
    clock.now = clock_at("15:58", EXP)
    rec.run()
    position = rec.store.positions()[0]
    snaps = rec.store.snapshots(position["key"])
    expiry = next(s for s in snaps if s["role"] == "expiry")
    assert expiry["status"] == "unavailable" and "never quoted" in expiry["note"]
    assert not er.score(position, snaps)["complete"]


def test_an_entry_seen_late_joins_the_position_its_add_opened(engine, tmp_path):
    clock = Clock(clock_at("09:59"))
    rec = recorder(engine, tmp_path, clock, Chains())
    fill(engine, "10:05")
    clock.now = clock_at("10:06")
    rec.run()
    fill(engine, "10:00")  # an earlier entry whose email came later
    clock.now = clock_at("10:07")
    rec.run()
    positions = rec.store.positions()
    assert len(positions) == 1
    assert [s["role"] for s in rec.store.snapshots(positions[0]["key"])] == ["entry", "entry"]


class HalfDay:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 780 if day == EXP else 960}


def test_a_half_day_closes_at_its_own_close(engine, tmp_path):
    clock = Clock(clock_at("09:59"))
    rec = recorder(engine, tmp_path, clock, Chains(), HalfDay())
    fill(engine, "10:00")
    clock.now = clock_at("10:01")
    rec.run()
    clock.now = clock_at("12:58", EXP)
    rec.run()
    snaps = rec.store.snapshots(rec.store.positions()[0]["key"])
    assert any(s["role"] == "expiry" and s["executed_at"].endswith("12:58:00") for s in snaps)
    clock.now = clock_at("13:30", EXP)
    rec._last_run = 0
    rec.run()  # after the half-day close plus 15 minutes: nothing runs
    assert rec.close_minute(date(2026, 10, 24)) is None  # a Saturday


def test_an_unusable_path_turns_off_only_the_recorder(engine, tmp_path, monkeypatch):
    (tmp_path / "plain").write_text("x")
    monkeypatch.setenv("EXPRESSION_RECORDER_ENABLED", "true")
    monkeypatch.setenv("EXPRESSION_RECORDER_PATH", str(tmp_path / "plain" / "x.sqlite3"))
    assert LevelAlertMonitor(engine).expressions is None
