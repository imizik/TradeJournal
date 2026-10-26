"""Pure calculation core for the proposed ETF/BIL exploration.

No loader, CLI, Factory intake or live execution. Callers must supply a reviewed
calendar and normalized actions; this module does not certify their provenance.
Only invented inputs are authorized for execution during preparation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction

SYMBOLS = ("SPY", "EFA", "EEM", "IEF", "BIL")
ZERO, ONE = Decimal(0), Decimal(1)
QUARTER = Decimal("0.25")
COSTS = (Decimal("0.001"), Decimal("0.003"))
CUTOFF = date(2024, 9, 30)
Vector = tuple[Decimal, ...]


def vector(values: Vector, *, positive=False, raw=False) -> None:
    if (not isinstance(values, tuple) or len(values) != len(SYMBOLS)
            or any(not isinstance(x, Decimal) or not x.is_finite() or x < 0
                   or x > Decimal("1e12")
                   or (raw and (x.as_tuple().exponent < -18 or len(x.as_tuple().digits) > 32))
                   or (positive and x == 0) for x in values)):
        raise ValueError("five finite nonnegative Decimal values required")


@dataclass(frozen=True)
class Session:
    day: date
    close: Vector
    # Explicit zero/one values are required. Missing action evidence is not zero.
    distribution: Vector  # entitlement per POST-event share, ex-date basis
    split: Vector  # post-event shares per prior share


@dataclass(frozen=True)
class Point:
    day: date
    nav: Decimal
    bil_weight: Decimal
    traded_notional: Decimal
    fee: Decimal


@dataclass(frozen=True)
class Decision:
    observed: date
    execution: date
    weights: Vector


@dataclass(frozen=True)
class Lane:
    path: tuple[Point, ...]
    monthly_returns: tuple[Decimal, ...]
    cagr: Decimal
    max_drawdown: Decimal
    traded_notional: Decimal
    fees: Decimal


@dataclass(frozen=True)
class Calculation:
    cost_rate: Decimal
    decisions: tuple[Decision, ...]
    active: Lane
    passive: Lane
    bil: Lane
    annualized_increment_pp: Decimal


def rebalance(holdings: Vector, cash: Decimal, weights: Vector,
              cost: Decimal) -> tuple[Vector, Decimal, Decimal]:
    """Solve V+ + c * sum(abs(w*V+ - H)) = V-, without borrowing fees."""
    vector(holdings)
    vector(weights)
    if (not isinstance(cash, Decimal) or not cash.is_finite() or cash < 0
            or not isinstance(cost, Decimal) or not cost.is_finite() or not 0 <= cost < 1
            or sum(weights) != 1):
        raise ValueError("invalid cash, cost or fully invested target weights")
    with localcontext() as context:
        context.prec = 40
        nav = sum(holdings) + cash
        if nav <= 0:
            raise ValueError("positive NAV required")
        lo, hi = ZERO, nav
        # Continuous and strictly increasing for c < 1 and sum(w)=1.
        for _ in range(160):
            mid = (lo + hi) / 2
            residual = mid + cost * sum(abs(w * mid - h) for w, h in zip(weights, holdings)) - nav
            if residual > 0:
                hi = mid
            else:
                lo = mid
        post = (lo + hi) / 2
        target = tuple(w * post for w in weights)
        traded = sum(abs(v - h) for v, h in zip(target, holdings))
        fee = cost * traded
        if abs(sum(target) + fee - nav) > nav * Decimal("1e-35"):
            raise ArithmeticError("self-financing residual")
        return target, traded, fee


def validate_sessions(rows: tuple[Session, ...], expected: tuple[date, ...]) -> tuple[int, ...]:
    """Expected sessions come from an independently reviewed calendar, not bars."""
    if (not rows or len(rows) > 2500 or not isinstance(expected, tuple)
            or any(type(d) is not date for d in expected)
            or tuple(sorted(set(expected))) != expected
            or any(d < date(2016, 1, 1) or d > CUTOFF for d in expected)
            or tuple(r.day for r in rows) != expected):
        raise ValueError("missing, duplicate, unordered or out-of-window sessions")
    for row in rows:
        vector(row.close, positive=True, raw=True)
        vector(row.distribution, raw=True)
        vector(row.split, positive=True, raw=True)
    months = [12 * d.year + d.month for d in expected]
    ends = tuple(i for i in range(len(rows)) if i == len(rows)-1 or months[i+1] != months[i])
    if len(ends) < 14 or any(months[b] - months[a] != 1 for a, b in zip(ends, ends[1:])):
        raise ValueError("13 warm-up month-ends and contiguous outcome months required")
    return ends


def calculate(rows: tuple[Session, ...], expected: tuple[date, ...]) -> tuple[Calculation, ...]:
    """Fixed 12-month signal, three paired lanes, both costs; never a gate verdict.

    Normalized actions must already resolve same-day units/duplicates and refuse
    unsupported events. This pure API is not a substitute for counted intake.
    Partial-month calendars must be rejected by the future bundle admission.
    """
    ends = validate_sessions(rows, expected)
    with localcontext() as context:
        context.prec = 40
        # Exact rational ratios preserve strict economic ties. A Decimal price
        # round trip such as 13 -> 19 -> 13 can otherwise round above one.
        index = [(Fraction(1),) * len(SYMBOLS)]
        daily_growth = [(ONE,) * len(SYMBOLS)]
        for previous, current in zip(rows, rows[1:]):
            growth = tuple(Fraction(split) * (Fraction(close) + Fraction(dividend)) / Fraction(old)
                           for split, close, dividend, old in zip(
                               current.split, current.close, current.distribution, previous.close))
            index.append(tuple(v*g for v, g in zip(index[-1], growth)))
            daily_growth.append(tuple(Decimal(g.numerator)/Decimal(g.denominator) for g in growth))
        decisions = []
        for month in range(12, len(ends)-1):
            now, old = ends[month], ends[month-12]
            growth = tuple(a/b for a, b in zip(index[now], index[old]))
            risk = tuple(QUARTER if g > growth[-1] else ZERO for g in growth[:-1])
            decisions.append(Decision(rows[now].day, rows[now+1].day, (*risk, ONE-sum(risk))))
        targets = {d.execution: d.weights for d in decisions}
        result = []
        for cost in COSTS:
            lanes = []
            for mode in ("active", "passive", "bil"):
                held, cash = (ZERO,) * len(SYMBOLS), ONE
                points, monthly, last_month_nav = [], [], ONE
                for i in range(ends[12], len(rows)):
                    day = rows[i].day
                    if i > ends[12]:
                        held = tuple(h*g for h, g in zip(held, daily_growth[i]))
                    traded = fee = ZERO
                    # Existing holdings first earn this session's return.
                    if day in targets:
                        weights = targets[day] if mode == "active" else (
                            (QUARTER,) * 4 + (ZERO,) if mode == "passive" else (ZERO,) * 4 + (ONE,))
                        held, traded, fee = rebalance(held, cash, weights, cost)
                        cash = ZERO
                    if i == len(rows)-1:
                        liquidation = sum(held)
                        traded += liquidation
                        fee += cost * liquidation
                        cash += liquidation * (1-cost)
                        held = (ZERO,) * len(SYMBOLS)
                    nav = sum(held) + cash
                    if not nav.is_finite() or nav <= 0:
                        raise ArithmeticError("invalid portfolio NAV")
                    points.append(Point(day, nav, held[-1]/nav, traded, fee))
                    if i in ends[13:]:
                        monthly.append(nav/last_month_nav - 1)
                        last_month_nav = nav
                peak, drawdown = ONE, ZERO
                for p in points:
                    peak = max(peak, p.nav)
                    drawdown = max(drawdown, 1-p.nav/peak)
                lanes.append(Lane(tuple(points), tuple(monthly),
                                  points[-1].nav ** (Decimal(12)/len(monthly)) - 1,
                                  drawdown, sum(p.traded_notional for p in points), sum(p.fee for p in points)))
            active, passive, bil = lanes
            increment = Decimal(1200) * sum(a-b for a, b in zip(active.monthly_returns, passive.monthly_returns)) / len(active.monthly_returns)
            result.append(Calculation(cost, tuple(decisions), active, passive, bil, increment))
        return tuple(result)
