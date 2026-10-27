"""Sealed SPY/QQQ v1: invented examples only, no strategy performance measured.

The subject is a test-only executable specification, not app/Factory code.
Expected outcomes below are hand-calculated and never imported from a backtest.
"""

import ast
import hashlib
import socket
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from tests.scalp_fixtures.execution import (
    Chain, Contract, ExitExample, PortfolioExample, Position, Print, Quote,
    accounting, enter, reference, select, unresolved_accounting,
)
from tests.scalp_fixtures.signal import Bar, ET, Session, Signal, SignalExample, trend_side

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = Path(__file__).parent / "scalp_fixtures"
DAY = date(2030, 1, 4)  # Invented Friday; no historical prices or market calendar call.


def at(hour=9, minute=47, second=0, *, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ET).astimezone(timezone.utc)


def session(**changes):
    return replace(Session(at(9, 30), at(16, 0)), **changes)


def signal(side=1, symbol="SPY", **changes):
    return replace(Signal(symbol, side, at(second=5), D("102.5") if side == 1 else D("97.5")), **changes)


def contract(side=1, symbol="SPY", strike=None, dte=3, **changes):
    strike = D(str(strike if strike is not None else (102 if side == 1 else 98)))
    expiry = DAY + timedelta(days=dte)
    occ = f"{symbol}{expiry:%y%m%d}{'C' if side == 1 else 'P'}{int(strike * 1000):08d}"
    return replace(Contract(occ, symbol, expiry, side, strike, root=symbol, deliverable=f"100 {symbol}"), **changes)


def trade(price="103", when=None, **changes):
    when = when or at(second=8)
    return replace(Print("SPY", when, when, D(price)), **changes)


def quote(when=None, bid="2.98", ask="3.02", **changes):
    when = when or at(second=10)
    return replace(Quote(contract().occ, when, when, when, D(bid), D(ask)), **changes)


def bar(index, close, *, high=None, low=None, side=1, **changes):
    close = D(str(close))
    high = D(str(high)) if high is not None else close + D("0.1")
    low = D(str(low)) if low is not None else close - D("0.1")
    if side == -1:
        close, high, low = 200 - close, 200 - low, 200 - high
    start = at(9, 30) + timedelta(minutes=index)
    return replace(Bar(start, start + timedelta(minutes=1, seconds=1), close, high, low, close, D(100)), **changes)


def warm(side=1, symbol="SPY"):
    engine = SignalExample(session(), symbol)
    for i in range(15):
        b = bar(i, D(100) + D("0.2") * (i + 1), side=side)
        assert engine.minute(b, b.end + timedelta(seconds=5)) is None
    assert engine.side == side and engine.trace == ["armed"]
    return engine


def decide(engine, close, **kwargs):
    b = bar(len(engine.bars), close, side=engine.side, **kwargs)
    return engine.minute(b, b.end + timedelta(seconds=5))


def position(side=1, symbol="SPY"):
    s, c = signal(side, symbol), contract(side, symbol)
    return Position(s, c, quote(occ=c.occ), D(103) if side == 1 else D(97))


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("fixture conformance cannot use network")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def test_sealed_documents_unchanged():
    folder = ROOT / "research/notes/spy-qqq-scalp-v1"
    expected = {
        "spec.md": "493340d39cb11cd6358f79cc3e58f7accb1febe6105a62aecee1ed0811c926bc",
        "prior-trial-audit.json": "db68ae5a88aca1e407c0e5347184287430a2a7476c40f66575931d9b3406ab77",
    }
    assert (folder / "freeze.sha256").read_text().splitlines() == [f"{sha}  {name}" for name, sha in expected.items()]
    for name, sha in expected.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == sha


def imports_are_fixture_only(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in {"dataclasses", "datetime", "decimal", "zoneinfo"} for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert ((node.level == 1 and node.module == "signal") or
                    (node.level == 0 and node.module in {"dataclasses", "datetime", "decimal", "zoneinfo"}))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "eval", "exec", "compile", "__import__", "input"}


def test_all_support_modules_are_pure_and_not_shipped_as_app_code():
    # Enumerate the directory, rather than a sample list of the current files.
    for path in SUPPORT.rglob("*.py"):
        imports_are_fixture_only(path.read_text())
    assert not list((ROOT / "backend/app").rglob("*scalp_fixtures*"))
    with pytest.raises(AssertionError, match="fixture conformance"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.parametrize("source", ["import socket", "from app.engine.factory_rules import run_candidate",
                                    "from pathlib import Path", "open('ledger', 'w')", "__import__('os')"])
def test_isolation_guard_rejects_planted_io_and_factory_imports(source):
    with pytest.raises(AssertionError):
        imports_are_fixture_only(source)


@pytest.mark.parametrize("side,symbol", [(1, "SPY"), (-1, "SPY"), (1, "QQQ"), (-1, "QQQ")])
def test_first_pullback_trigger_is_mirrored_and_stop_excludes_trigger(side, symbol):
    engine = warm(side, symbol)
    assert not engine.pullback
    assert decide(engine, "102.8", high="102.95", low="102.5") is None
    result = decide(engine, "103.1", high="103.2", low="102.6")
    assert result == signal(side, symbol)
    assert engine.retired and engine.trace == ["armed", "pullback", "trigger"]
    # Neither another pullback nor a previously rejected opportunity can rearm.
    before = tuple(engine.bars)
    assert decide(engine, "104") is None
    assert tuple(engine.bars) == before


@pytest.mark.parametrize("side", [1, -1])
def test_three_pullbacks_then_confirmation_allowed(side):
    engine = warm(side)
    for value in ("102.9", "102.8", "102.7"):
        assert decide(engine, value) is None
    result = decide(engine, "103.1", low="102.65")
    assert result.side == side
    assert result.stop == (D("102.6") if side == 1 else D("97.4"))
    assert len(engine.pullback) == 3


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("failure", ["fourth", "equal", "not_clear", "extreme_equal", "vwap_touch", "stop_touch"])
def test_first_pullback_failure_retires_day(side, failure):
    engine = warm(side)
    decide(engine, "102.8", high="103", low="102.5")
    if failure == "fourth":
        for v in ("102.7", "102.6", "102.5"):
            decide(engine, v)
    elif failure == "equal":
        decide(engine, "102.8")
    elif failure == "not_clear":
        decide(engine, "102.9")
    elif failure == "extreme_equal":
        decide(engine, "103")
    elif failure == "vwap_touch":
        decide(engine, "103.1", low="100")
    else:
        decide(engine, "103.1", low="102.5")
    assert engine.retired
    assert "trigger" not in engine.trace
    assert decide(engine, "104") is None


def test_neutral_before_pullback_allowed_but_boundary_trend_failure_precedes_trigger():
    engine = warm()
    decide(engine, "103")
    assert not engine.pullback and not engine.retired
    decide(engine, "103.2")
    decide(engine, "103.1")
    decide(engine, "102.8", high="102.9")
    assert decide(engine, "103", low="102.75") is None  # Would clear prior high.
    assert engine.trace[-1] == "trend_failed"  # 09:50 close equals 09:45 close.


@pytest.mark.parametrize("side", [1, -1])
def test_exact_vwap_touch_retires_and_eleven_oclock_bar_cannot_trigger(side):
    engine = warm(side)
    decide(engine, "103.1", low="101.6", volume=D(0))
    assert engine.trace[-1] == "vwap_failed"
    engine = warm(side)
    # Invented rising closes retain the trend without creating a pullback.
    while len(engine.bars) < 88:
        decide(engine, D(100) + D("0.2") * (len(engine.bars) + 1))
    assert not engine.retired
    decide(engine, "117.5", high="117.7", low="117.3")  # 10:59 first adverse close
    assert decide(engine, "118", low="117.4") is None  # 11:00 close cannot signal
    assert engine.trace[-1] == "window_closed"


def test_trend_uses_each_own_vwap_strictly_and_bar_vwap_is_volume_weighted():
    assert trend_side([(D(101), D(100)), (D(102), D(101)), (D(103), D(102))]) == 1
    assert trend_side([(D(101), D(101)), (D(102), D(101)), (D(103), D(102))]) == 0
    assert trend_side([(D(101), D(100)), (D(101), D(100)), (D(103), D(102))]) == 0
    engine = SignalExample(session(), "SPY")
    first = bar(0, "100", high="103", low="97", volume=D(2))
    second = bar(1, "103", high="106", low="100", volume=D(1))
    for b in (first, second):
        engine.minute(b, b.end + timedelta(seconds=5))
    assert engine.total_value / engine.total_volume == D(101)
    zero = SignalExample(session(), "SPY")
    for i in range(15):
        b = bar(i, 100 + i, volume=D(0))
        zero.minute(b, b.end + timedelta(seconds=5))
    assert zero.side == 0 and zero.five_ends[-1][1] is None


@pytest.mark.parametrize("fault", ["missing", "late", "future", "naive", "bad_ohlc", "nan", "negative_volume", "duplicate", "decision_late"])
def test_bad_minute_invalidates_day_without_rewriting_decided_bars(fault):
    engine = warm()
    old = tuple(engine.bars)
    b = bar(15, "102.8")
    decision = b.end + timedelta(seconds=5)
    if fault == "missing":
        b = None
    elif fault == "late":
        b = replace(b, received=decision + timedelta(microseconds=1))
    elif fault == "future":
        b = replace(b, received=b.end - timedelta(microseconds=1))
    elif fault == "naive":
        b = replace(b, received=b.received.replace(tzinfo=None))
    elif fault == "bad_ohlc":
        b = replace(b, low=D(200))
    elif fault == "nan":
        b = replace(b, close=D("NaN"))
    elif fault == "negative_volume":
        b = replace(b, volume=D(-1))
    elif fault == "duplicate":
        b = replace(engine.bars[-1], close=D("102.95"))
    else:
        decision += timedelta(microseconds=1)
    assert engine.minute(b, decision) is None
    assert engine.trace[-1] == "invalid_or_missing_minute"
    assert tuple(engine.bars) == old


@pytest.mark.parametrize("changes", [dict(calendar_verified=False), dict(clock_error_ms=None), dict(clock_error_ms=101),
                                    dict(healthy=False), dict(halted=True), dict(stock_feed="iex"),
                                    dict(option_feed="indicative"), dict(opened=at(10, 0)), dict(closed=at(11, 15))])
def test_ineligible_session_refuses_signals(changes):
    engine = SignalExample(session(**changes), "SPY")
    b = bar(0, 100)
    assert engine.minute(b, b.end + timedelta(seconds=5)) is None
    assert engine.trace == ["ineligible_session"]


def test_verified_early_close_and_clock_boundary_allowed():
    assert session(closed=at(13, 0), clock_error_ms=100).eligible()
    assert not session(clock_error_ms=-101).eligible()


@pytest.mark.parametrize("side,symbol,strike", [(1, "SPY", 102), (-1, "SPY", 104), (1, "QQQ", 102), (-1, "QQQ", 104)])
def test_selection_earliest_calendar_expiry_strictly_itm_no_delta_needed(side, symbol, strike):
    assert DAY.weekday() == 4
    s = signal(side, symbol)
    contracts = tuple(contract(side, symbol, k, dte=d) for d in (0, 1, 3, 4, 5, 6) for k in (101, 102, 103, 104, 105))
    c = Chain(at(second=8), contracts)
    status, selected, intent = select(s, session(), [c], [trade(symbol=symbol)], at(second=15))
    assert status == "selected" and selected.strike == strike
    assert selected.expiry == date(2030, 1, 7)  # Friday -> Monday = 3 calendar days.
    assert intent == c.received


@pytest.mark.parametrize("dte,expected", [(0, "no_expiry"), (1, "no_expiry"), (2, "selected"), (5, "selected"), (6, "no_expiry")])
def test_dte_boundaries_use_listing_not_assumed_weekday(dte, expected):
    status, _, _ = select(signal(), session(), [Chain(at(second=8), (contract(dte=dte),))], [trade()], at(second=15))
    assert status == expected


@pytest.mark.parametrize("change", [dict(multiplier=None), dict(multiplier=10), dict(deliverable=None),
                                   dict(deliverable="50 SPY"), dict(root="SPY1"), dict(currency="EUR"), dict(occ="conflicting")])
def test_uncertain_nearer_contract_cannot_be_skipped_for_farther(change):
    contracts = (contract(strike=101), contract(strike=102, **change))
    result = select(signal(), session(), [Chain(at(second=8), contracts)], [trade()], at(second=15))
    assert result[0] == "contract_data_error"


def test_adjusted_excluded_duplicates_refused_and_no_farther_expiry_fallback():
    s, c = signal(), contract()
    def choose(items):
        return select(s, session(), [Chain(at(second=8), tuple(items))], [trade()], at(second=15))
    assert choose([replace(c, adjusted=True)])[0] == "no_expiry"
    assert choose([c, c])[0] == "contract_data_error"
    assert choose([contract(strike=103), contract(dte=4)])[0] == "no_itm"
    assert choose([contract(side=-1)])[0] == "no_expiry"
    assert choose([contract(symbol="QQQ")])[0] == "no_expiry"
    assert choose([contract(strike=101, deliverable=None), c])[1] == c


def test_first_complete_chain_and_deadline_are_not_shopped():
    s = signal()
    chains = [Chain(at(second=6), (), complete=False), Chain(at(second=8), ()), Chain(at(second=9), (contract(),))]
    assert select(s, session(), chains, [trade()], at(second=15))[0] == "no_expiry"
    assert select(s, session(), [], [], at(second=14))[0] == "pending"
    assert select(s, session(), [], [], at(second=15))[0] == "no_chain"
    late = Chain(at(second=16), (contract(),))
    assert select(s, session(), [late], [trade()], at(second=16))[0] == "no_chain"
    exact = Chain(at(second=15), (contract(),))
    assert select(s, session(), [exact], [trade(when=at(second=15))], at(second=15))[0] == "selected"
    assert select(s, session(), [replace(exact, received=s.at)], [trade()], at(second=15))[0] == "no_chain"


@pytest.mark.parametrize("fault", ["missing", "stale", "ambiguous", "unknown", "future", "out_of_session", "bad_size"])
def test_underlying_reference_must_be_available_fresh_and_interpretable(fault):
    p = trade()
    prints = [p]
    if fault == "missing":
        prints = []
    elif fault == "stale":
        prints = [replace(p, source=p.source - timedelta(seconds=3))]
    elif fault == "ambiguous":
        prints = [p, replace(p, price=D(104), sequence=None)]
    elif fault == "unknown":
        prints = [replace(p, conditions_known=False)]
    elif fault == "future":
        prints = [replace(p, source=p.received + timedelta(microseconds=1))]
    elif fault == "out_of_session":
        prints = [replace(p, source=at(9, 29))]
    else:
        prints = [replace(p, size=D(0))]
    assert select(signal(), session(), [Chain(p.received, (contract(),))], prints, at(second=15))[0] == "no_underlying_reference"


def test_reference_ignores_cancelled_wrong_symbol_and_uses_reliable_tie_sequence():
    p = trade()
    assert reference([p, replace(p, cancelled=True, price=D(100))], session(), "SPY", p.received) == p
    assert reference([replace(p, symbol="QQQ")], session(), "SPY", p.received) is None
    later = replace(p, price=D(104), sequence=2)
    assert reference([later, p], session(), "SPY", p.received) == later


def entry(quotes=None, prints=None, **kwargs):
    return enter(signal(), contract(), at(second=8), session(), quotes if quotes is not None else [quote()],
                 prints if prints is not None else [trade(when=at(second=10))], kwargs.pop("through", at(second=18)), **kwargs)


def test_entry_ask_latency_target_and_premium_accounting_hand_calculated():
    status, p = entry()
    assert status == "entered"
    assert p.entry.ask == D("3.02") and p.entry.received == at(second=10)
    assert p.underlying == D(103) and p.signal.stop == D("102.5") and p.target == D("103.75")
    assert p.debit == D(303)
    result = accounting(p, quote(bid="3.50", ask="3.54"))
    assert result == {"net": D(46), "return_on_premium": D(46) / D(302), "debit": D(303),
                      "stress_net": D(38), "stress_return": D(38) / D(306)}
    assert unresolved_accounting([p]) == {"count": 1, "entry_debit_at_risk": D(303), "full_loss_sensitivity": D(-304)}


@pytest.mark.parametrize("fault", ["early", "late", "old_bid", "old_ask", "stale_bid", "stale_ask", "future", "crossed", "zero_bid", "zero_size", "ask_size", "wrong_contract", "indicative", "nan"])
def test_invalid_entry_quotes_never_fill_but_next_valid_can(fault):
    q = quote()
    bad = {
        "early": replace(q, received=at(second=9), bid_at=at(second=9), ask_at=at(second=9)),
        "late": replace(q, received=at(second=19), bid_at=at(second=19), ask_at=at(second=19)),
        "old_bid": replace(q, bid_at=at(second=9)), "old_ask": replace(q, ask_at=at(second=9)),
        "stale_bid": replace(q, received=at(second=13), ask_at=at(second=13)),
        "stale_ask": replace(q, received=at(second=13), bid_at=at(second=13)),
        "future": replace(q, ask_at=at(second=11)), "crossed": replace(q, bid=D(4)),
        "zero_bid": replace(q, bid=D(0)), "zero_size": replace(q, bid_size=0), "ask_size": replace(q, ask_size=0),
        "wrong_contract": replace(q, occ=contract(strike=101).occ), "indicative": replace(q, feed="indicative"),
        "nan": replace(q, ask=D("NaN")),
    }[fault]
    assert entry([bad])[0] == "unfilled_quote"
    good = quote(when=at(second=14))
    assert entry([bad, good], [trade(when=at(second=14))])[1].entry == good


@pytest.mark.parametrize("bid,ask,expected", [("2.475", "2.525", "entered"), ("2.4749", "2.525", "spread_rejected"),
                                           ("1.99", "2.04", "spread_rejected"), ("3", "3", "entered")])
def test_spread_thresholds_are_inclusive_and_both_apply(bid, ask, expected):
    assert entry([quote(bid=bid, ask=ask)])[0] == expected


def test_first_valid_wide_quote_rejects_without_waiting_or_contract_switch():
    bad = quote(bid="2.90", ask="3.02")
    good = quote(when=at(second=11))
    assert entry([bad, good])[0] == "spread_rejected"
    assert entry([quote(occ=contract(strike=101).occ)])[0] == "unfilled_quote"


@pytest.mark.parametrize("side", [1, -1])
def test_stop_touch_then_recovery_cancels_entry(side):
    s, c = signal(side), contract(side)
    touched = trade(str(s.stop), when=at(second=9))
    recovered = trade("103" if side == 1 else "97", when=at(second=10))
    result = enter(s, c, at(second=8), session(), [quote(occ=c.occ)], [touched, recovered], at(second=18))
    assert result == ("stop_before_entry", None)


def test_entry_cannot_substitute_later_reference_or_unknown_health():
    assert entry(prints=[])[0] == "unfilled_reference"
    assert entry(prints=[trade(when=at(second=11))])[0] == "unfilled_reference"
    assert entry(healthy=False)[0] == "unfilled_health_or_order"
    assert entry(ordering_known=False)[0] == "unfilled_health_or_order"
    assert entry(through=at(second=9))[0] == "pending"
    assert entry([quote(when=at(second=18))], [trade(when=at(second=18))])[0] == "entered"
    late_signal = signal(at=at(10, 59, 55))
    result = enter(late_signal, contract(), at(10, 59, 58), session(), [quote(when=at(11, 0))],
                   [trade(when=at(11, 0))], at(11, 0, 8))
    assert result[0] == "unfilled_window"


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("reason", ["stop", "target"])
def test_exit_crosses_are_inclusive_mirrored_and_receipt_time_is_intent(side, reason):
    p = position(side)
    runner = ExitExample(p, session())
    price = p.signal.stop if reason == "stop" else p.target
    event = trade(str(price), when=at(second=13), source=at(second=12))
    runner.batch(event.received, [event])
    assert runner.reason == reason and runner.intent == at(second=13)
    runner.batch(at(second=14), [trade("100", when=at(second=14))])
    assert runner.intent == at(second=13)


def test_delayed_preentry_print_cannot_cross_but_stale_or_unknown_print_is_unresolved():
    runner = ExitExample(position(), session())
    p = trade("100", when=at(second=11), source=at(second=9))
    runner.batch(p.received, [p])
    assert runner.intent is None and not runner.unresolved
    runner.batch(at(second=14), [trade("100", when=at(second=14), source=at(second=11))])
    assert runner.unresolved and runner.reason == "unresolved_reference"
    other = ExitExample(position(), session())
    other.batch(at(second=12), [trade("100", when=at(second=12), conditions_known=False)])
    assert other.unresolved


@pytest.mark.parametrize("sequences,expected", [((1, 2), "stop"), ((2, 1), "target"), ((None, None), "unresolved_event_order"), ((1, 1), "unresolved_event_order")])
def test_same_receipt_both_crosses_need_reliable_sequence(sequences, expected):
    runner = ExitExample(position(), session())
    t = at(second=13)
    runner.batch(t, [trade("102.5", when=t, sequence=sequences[0]), trade("103.75", when=t, sequence=sequences[1])])
    assert runner.reason == expected
    assert runner.unresolved == expected.startswith("unresolved")


@pytest.mark.parametrize("reason,price", [("time", "103"), ("stop", "102.5"), ("target", "103.75")])
def test_timer_fifteen_elapsed_minutes_and_known_cross_tie_precedence(reason, price):
    runner = ExitExample(position(), session())
    due = at(10, 2, 10)
    runner.batch(due - timedelta(microseconds=1))
    assert runner.intent is None
    runner.batch(due, [trade(price, when=due)])
    assert runner.intent == due and runner.reason == reason


def test_absolute_cutoff_and_missed_timer_are_not_backfilled():
    # Defensive fabricated position: normal entry guard already forbids 11:00.
    p = replace(position(), entry=quote(when=at(11, 1)))
    runner = ExitExample(p, session())
    runner.batch(at(11, 15))
    assert runner.reason == "time" and runner.intent == at(11, 15)
    missed = ExitExample(position(), session())
    missed.batch(at(10, 2, 11))
    assert missed.unresolved and missed.intent is None


def exit_example():
    runner = ExitExample(position(), session())
    runner.batch(at(second=13), [trade("102.5", when=at(second=13))])
    return runner


def test_exit_uses_bid_without_spread_cap_and_primary_is_immutable():
    runner = exit_example()
    wide = quote(when=at(second=15), bid="0.10", ask="2.50")
    assert runner.liquidate([wide], at(second=23)) == ("resolved", wide)
    assert accounting(runner.position, wide)["net"] == D(-294)
    assert accounting(runner.position, wide)["stress_net"] == D(-308)  # stress bid floors at zero
    runner.health(healthy=False, heartbeat_gap_seconds=99)
    assert runner.liquidate([quote(when=at(second=16), bid="4", ask="4")], at(second=24)) == ("resolved", wide)


@pytest.mark.parametrize("fault", ["zero_bid", "zero_size", "old_bid", "old_ask", "late", "missing"])
def test_exit_deadline_leaves_exposure_unresolved_and_later_quotes_cannot_repair(fault):
    runner = exit_example()
    q = quote(when=at(second=15))
    bad = {"zero_bid": [replace(q, bid=D(0))], "zero_size": [replace(q, bid_size=0)],
           "old_bid": [replace(q, bid_at=at(second=14))], "old_ask": [replace(q, ask_at=at(second=14))],
           "late": [quote(when=at(second=24))], "missing": []}[fault]
    assert runner.liquidate(bad, at(second=22)) == ("pending", None)
    assert runner.liquidate(bad, at(second=23)) == ("unresolved", None)
    assert runner.liquidate([quote(when=at(second=24))], at(second=24)) == ("unresolved", None)
    assert runner.position.debit == D(303)
    assert runner.reason == "stop" and runner.unresolved_reason == "unresolved_exit"


def test_exit_exact_deadline_allowed_and_unknown_quote_order_refused():
    runner = exit_example()
    exact = quote(when=at(second=23))
    assert runner.liquidate([exact], at(second=23)) == ("resolved", exact)
    runner = exit_example()
    assert runner.liquidate([exact, replace(exact, bid=D("2.97"))], at(second=23)) == ("unresolved", None)


@pytest.mark.parametrize("healthy,gap,halted,unresolved", [(True, 5, False, False), (True, 5.001, False, True),
                                                       (False, 0, False, True), (True, 0, True, True)])
def test_health_gap_not_quiet_stream_makes_exposure_unresolved(healthy, gap, halted, unresolved):
    runner = ExitExample(position(), session())
    runner.health(healthy=healthy, heartbeat_gap_seconds=gap, halted=halted)
    assert runner.unresolved == unresolved
    if not unresolved:
        runner.batch(at(10, 2, 10))  # No prints with verified health: timed exit.
        assert runner.reason == "time"


def test_spy_wins_simultaneous_batch_even_when_it_later_fails_no_qqq_fallback():
    book = PortfolioExample(session())
    assert book.admit([signal(symbol="QQQ"), signal()]) == signal()
    assert book.dispositions == [("SPY", "reserved"), ("QQQ", "skipped_simultaneous")]
    book.entry_result("no_expiry")
    assert book.state == "flat"
    assert book.admit([signal(symbol="QQQ", at=at(9, 48, 5))]) is None
    assert book.dispositions[-1] == ("QQQ", "already_used")


def test_unknown_disposition_cannot_release_reserved_exposure():
    book = PortfolioExample(session())
    book.admit([signal()])
    with pytest.raises(ValueError, match="unknown entry disposition"):
        book.entry_result("surprise")
    assert book.state == "reserved"


@pytest.mark.parametrize("state", ["reserved", "open", "unresolved"])
def test_busy_trigger_is_consumed_and_never_queued(state):
    book = PortfolioExample(session())
    book.admit([signal()])
    if state in ("open", "unresolved"):
        book.entry_result("entered")
    if state == "unresolved":
        book.exit_result("unresolved")
    assert book.admit([signal(symbol="QQQ", at=at(9, 48, 5))]) is None
    assert book.dispositions[-1] == ("QQQ", "skipped_busy")
    assert book.used == {"SPY", "QQQ"}


def test_two_resolved_entries_then_reset_but_unresolved_blocks_next_session():
    book = PortfolioExample(session())
    for symbol, minute in (("SPY", 47), ("QQQ", 49)):
        assert book.admit([signal(symbol=symbol, at=at(9, minute, 5))])
        book.entry_result("entered")
        book.exit_result("resolved")
    assert book.entries == 2 and book.state == "flat"
    assert book.admit([signal(at=at(9, 51, 5))]) is None
    next_day = date(2030, 1, 7)
    next_session = Session(at(9, 30, day=next_day), at(16, 0, day=next_day))
    book.next_session(next_session)
    assert not book.used and book.entries == 0 and book.state == "flat"
    s = signal(at=at(9, 47, 5, day=next_day))
    assert book.admit([s])
    book.entry_result("entered")
    book.exit_result("unresolved")
    next_day = date(2030, 1, 8)
    book.next_session(Session(at(9, 30, day=next_day), at(16, 0, day=next_day)))
    assert book.state == "unresolved"
    assert book.admit([signal(at=at(9, 47, 5, day=next_day))]) is None
    assert book.dispositions[-1][1] == "skipped_busy"


@pytest.mark.parametrize("side,symbol", [(1, "SPY"), (-1, "QQQ")])
def test_complete_invented_signal_to_resolved_cash_trace(side, symbol):
    model, book = warm(side, symbol), PortfolioExample(session())
    decide(model, "102.8", high="102.95", low="102.5")
    s = decide(model, "103.1", low="102.6")
    assert book.admit([s]) == s
    c = contract(side, symbol)
    px = "103" if side == 1 else "97"
    chain = Chain(at(second=8), (c,))
    status, locked, intent = select(s, session(), [chain], [trade(px, symbol=symbol)], at(second=8))
    assert status == "selected" and locked == c
    q = quote(occ=c.occ)
    status, p = enter(s, c, intent, session(), [q], [trade(px, symbol=symbol, when=q.received)], q.received)
    book.entry_result(status)
    assert book.state == "open" and book.entries == 1
    runner = ExitExample(p, session())
    runner.batch(at(second=13), [trade(str(p.target), symbol=symbol, when=at(second=13))])
    assert runner.reason == "target"
    exit_q = quote(when=at(second=15), occ=c.occ, bid="3.50", ask="3.54")
    status, fill = runner.liquidate([exit_q], exit_q.received)
    book.exit_result(status)
    assert book.state == "flat" and accounting(p, fill)["net"] == D(46)
