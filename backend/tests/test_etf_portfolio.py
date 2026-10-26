"""Invented prices only; no archive/provider/ledger/backtest execution."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D, localcontext

import pytest

from app.engine.etf_portfolio import COSTS, Session, calculate, rebalance, validate_sessions

Z = (D(0),) * 5
ONES = (D(1),) * 5


def invented():
    # Sparse INVENTED calendar for unit calculations, never actual coverage proof.
    days = [date(2016, m, 28) for m in range(1, 13)] + [date(2017, 1, 31),
            date(2017, 2, 1), date(2017, 2, 28), date(2017, 3, 1), date(2017, 3, 31)]
    rows = tuple(Session(d, (D(100),) * 5, Z, ONES) for d in days)
    return rows, tuple(days)


def change(rows, index, *, symbol=0, close=None, dividend=None, split=None):
    row = rows[index]
    fields = {}
    for name, value in (("close", close), ("distribution", dividend), ("split", split)):
        if value is not None:
            values = list(getattr(row, name))
            values[symbol] = D(value)
            fields[name] = tuple(values)
    return rows[:index] + (replace(row, **fields),) + rows[index+1:]


def near(actual, expected):
    assert abs(actual - expected) < D("1e-28")


@pytest.mark.parametrize("cost", COSTS)
def test_cash_entry_no_trade_full_switch_and_no_fee_borrowing(cost):
    with localcontext() as ctx:
        ctx.prec = 40
        target = (D(1), D(0), D(0), D(0), D(0))
        bought, notional, fee = rebalance(Z, D(1), target, cost)
        near(sum(bought), 1/(1+cost))
        near(sum(bought) + fee, D(1))
        near(notional, bought[0])
        unchanged, traded, second_fee = rebalance(bought, D(0), target, cost)
        near(sum(unchanged), sum(bought))
        near(traded, D(0))
        near(second_fee, D(0))
        switched, traded, fee = rebalance(target, D(0), target[::-1], cost)
        near(sum(switched), (1-cost)/(1+cost))
        near(traded, 1+sum(switched))
        near(sum(switched) + fee, D(1))


def test_drift_rebalance_has_analytical_self_financing_solution():
    # Sell the overweight first sleeve and buy the second. Both sides pay costs.
    with localcontext() as ctx:
        ctx.prec = 40
        held = (D("0.75"), D("0.25"), D(0), D(0), D(0))
        target = (D("0.5"), D("0.5"), D(0), D(0), D(0))
        out, traded, fee = rebalance(held, D(0), target, D("0.001"))
        near(sum(out), D("0.9995"))
        near(traded, D("0.5"))
        near(fee, D("0.0005"))


@pytest.mark.parametrize("cash,cost,weights", [
    (D(-1), D(".001"), ONES), (D(1), D(1), (D(".2"),)*5),
    (D(1), D("NaN"), (D(".2"),)*5), (D(1), D(".001"), (D(".1"),)*5),
    (1.0, D(".001"), (D(".2"),)*5), (D(1), D(".001"), (D("Infinity"),)*5)])
def test_bad_financial_inputs_refuse(cash, cost, weights):
    with pytest.raises(ValueError):
        rebalance(Z, cash, weights, cost)


def test_flat_markets_tie_to_bil_and_charge_all_lanes_identically():
    rows, days = invented()
    outputs = calculate(rows, days)
    assert tuple(o.cost_rate for o in outputs) == COSTS
    for result in outputs:
        assert len(result.decisions) == 2
        assert all(d.weights == (D(0),)*4 + (D(1),) for d in result.decisions)
        with localcontext() as ctx:
            ctx.prec = 40
            expected = (1-result.cost_rate)/(1+result.cost_rate)
            for lane in (result.active, result.passive, result.bil):
                assert len(lane.monthly_returns) == 2
                near(lane.path[-1].nav, expected)
                near(lane.cagr, expected**6 - 1)
                near(lane.max_drawdown, 1-expected)
                near(lane.fees, 1-expected)
                assert lane.path[0].nav == 1
                assert lane.path[-1].bil_weight == 0  # terminal liquidation
            near(result.annualized_increment_pp, D(0))


def test_next_close_start_does_not_earn_the_first_session_jump():
    rows, days = invented()
    rows = change(rows, 12, close=110)  # only SPY > BIL at the decision
    for i in range(13, len(rows)):
        rows = change(rows, i, close=220)
    out = calculate(rows, days)[0]
    assert out.decisions[0].observed == days[12]
    assert out.decisions[0].execution == days[13]
    assert out.decisions[0].weights == (D(".25"), D(0), D(0), D(0), D(".75"))
    with localcontext() as ctx:
        ctx.prec = 40
        near(out.active.path[1].nav, 1/(1+out.cost_rate))


def test_existing_holdings_earn_execution_day_before_new_weights():
    rows, days = invented()
    # All four outperform on Jan31; switch to BIL after the Feb28 crash.
    rows = tuple(replace(r, close=(D(110),)*4 + (D(100),)) if i in (12, 13)
                 else r for i, r in enumerate(rows))
    rows = tuple(replace(r, close=(D(90),)*4 + (D(100),)) if i == 14 else r
                 for i, r in enumerate(rows))
    rows = tuple(replace(r, close=(D(180),)*4 + (D(100),)) if i >= 15 else r
                 for i, r in enumerate(rows))
    out = calculate(rows, days)[0]
    assert out.decisions[1].weights[-1] == 1
    before, after = out.active.path[2:4]
    with localcontext() as ctx:
        ctx.prec = 40
        # Old risk holdings double on March1, THEN sell into BIL, paying both sides.
        near(after.nav, before.nav * 2 * (1-out.cost_rate)/(1+out.cost_rate))
        assert after.bil_weight == 1


def test_ex_dividend_and_split_are_neutral_when_economic_value_is_flat():
    rows, days = invented()
    # On the first invested return day: 2 shares * (49 close + 1 dividend) = 100.
    rows = change(rows, 14, close=49, dividend=1, split=2)
    rows = change(rows, 15, close=49)
    rows = change(rows, 16, close=49)
    with localcontext() as ctx:
        ctx.prec = 40
        out = calculate(rows, days)[0]
        near(out.passive.path[1].nav, out.passive.path[2].nav)
        # Price-only treatment would incorrectly halve SPY's economic wealth.
        near(out.passive.path[-1].nav, (1-out.cost_rate)/(1+out.cost_rate))


def test_future_prices_cannot_change_earlier_targets_or_paths():
    rows, days = invented()
    modified = change(rows, len(rows)-1, close=9999)
    old, new = calculate(rows, days)[0], calculate(modified, days)[0]
    assert old.decisions == new.decisions
    for name in ("active", "passive", "bil"):
        assert getattr(old, name).path[:-1] == getattr(new, name).path[:-1]


def test_bil_reverse_split_does_not_create_a_cash_alternative_gain():
    rows, days = invented()
    rows = change(rows, 14, symbol=4, close=200, split=".5")
    rows = change(rows, 15, symbol=4, close=200)
    rows = change(rows, 16, symbol=4, close=200)
    out = calculate(rows, days)[0]
    with localcontext() as ctx:
        ctx.prec = 40
        for lane in (out.active, out.bil):
            near(lane.path[-1].nav, (1-out.cost_rate)/(1+out.cost_rate))


def test_strict_comparator_equal_growth_stays_in_bil():
    rows, days = invented()
    rows = change(change(rows, 12, close=101), 12, symbol=4, close=101)
    out = calculate(rows, days)[0]
    assert out.decisions[0].weights == (D(0),)*4 + (D(1),)


@pytest.mark.parametrize("ending,expected_weight", [("13", "0"), ("13.000000000000000001", ".25")])
def test_exact_round_trip_tie_and_genuine_tiny_gain(ending, expected_weight):
    rows, days = invented()
    rows = tuple(replace(r, close=(D(13),)*5) for r in rows)
    rows = change(rows, 1, close=19)
    rows = change(rows, 12, close=ending)
    out = calculate(rows, days)[0]
    assert out.decisions[0].weights[0] == D(expected_weight)
    assert out.decisions[0].weights[-1] == 1-D(expected_weight)


def test_paired_metric_uses_all_months_and_is_not_cagr_difference():
    rows, days = invented()
    rows = change(rows, 14, close=200)
    rows = change(rows, 15, close=200)
    rows = change(rows, 16, close=150)
    out = calculate(rows, days)[0]
    with localcontext() as ctx:
        ctx.prec = 40
        expected = D(600) * sum(a-b for a, b in zip(out.active.monthly_returns, out.passive.monthly_returns))
        near(out.annualized_increment_pp, expected)
    assert abs(out.annualized_increment_pp - 100*(out.active.cagr-out.passive.cagr)) > D(".01")


@pytest.mark.parametrize("kind", ["missing", "duplicate", "order", "protected", "incomplete_warmup", "gap", "nan", "float", "zero_split", "unbounded_scale"])
def test_calendar_and_numeric_refusals(kind):
    rows, days = invented()
    if kind == "missing":
        rows = rows[:3] + rows[4:]
    elif kind == "duplicate":
        rows = rows[:3] + (rows[3],) + rows[3:]
        days = tuple(r.day for r in rows)
    elif kind == "order":
        rows = rows[::-1]
        days = days[::-1]
    elif kind == "protected":
        rows += (replace(rows[-1], day=date(2024, 10, 1)),)
        days += (date(2024, 10, 1),)
    elif kind == "incomplete_warmup":
        rows, days = rows[:12], days[:12]
    elif kind == "gap":
        rows, days = rows[:3]+rows[4:], days[:3]+days[4:]
    else:
        row = rows[3]
        bad = {"nan": D("NaN"), "float": 100.0, "unbounded_scale": D("1e-1000000"), "zero_split": D(0)}
        field, value = ("split" if kind == "zero_split" else "close"), bad[kind]
        rows = rows[:3] + (replace(row, **{field: (value,)*5}),) + rows[4:]
    with pytest.raises(ValueError):
        validate_sessions(rows, days)
