"""Pure, deterministic calculations for Strategy Lab run metrics.

The functions in this module deliberately know nothing about SQLModel or a
database session.  Callers adapt persisted trades into :class:`MetricTrade`
instances and persist the returned values separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CALCULATION_VERSION = "strategy_metrics_v1"

_ZERO = Decimal("0")
_ONE_HUNDRED = Decimal("100")
_Q6 = Decimal("0.000001")
_NUMERIC_18_6_MAX = Decimal("999999999999.999999")

_TIME_BUCKETS = ("premarket", "open", "mid", "close", "afterhours", "unknown")


class MetricCalculationError(ValueError):
    """Raised when inputs cannot produce safe, persistable run metrics."""


@dataclass(frozen=True)
class MetricTrade:
    """Small, persistence-independent projection of one strategy trade."""

    trade_number: int
    direction: str
    entry_at: datetime | None = None
    exit_at: datetime | None = None
    net_pnl: Decimal | None = None
    return_pct: Decimal | None = None
    mfe: Decimal | None = None
    mae: Decimal | None = None
    duration_minutes: int | None = None
    cumulative_return_pct: Decimal | None = None


@dataclass(frozen=True)
class RunMetricResult:
    """Calculated values ready for scalar and canonical-JSON persistence."""

    calculation_version: str
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal | None
    average_winner: Decimal | None
    average_loser: Decimal | None
    payoff_ratio: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    total_net_pnl: Decimal | None
    net_return_pct: Decimal | None
    max_drawdown: Decimal | None
    max_drawdown_pct: Decimal | None
    average_mfe: Decimal | None
    median_mfe: Decimal | None
    average_mae: Decimal | None
    median_mae: Decimal | None
    average_holding_minutes: Decimal | None
    top_1_profit_contribution_pct: Decimal | None
    top_3_profit_contribution_pct: Decimal | None
    top_5_profit_contribution_pct: Decimal | None
    long_summary: dict[str, Any]
    short_summary: dict[str, Any]
    time_bucket_summary: dict[str, dict[str, Any]]
    coverage: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]
    findings: list[dict[str, Any]]


def _validate_decimal(value: Decimal | None, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal):
        raise MetricCalculationError(f"{label} must be a Decimal or None")
    if not value.is_finite():
        raise MetricCalculationError(f"{label} must be finite")


def _stored_decimal(value: Decimal | None, label: str) -> Decimal | None:
    """Round as persisted and reject values outside Numeric(18,6)."""
    if value is None:
        return None
    _validate_decimal(value, label)
    try:
        quantized = value.quantize(_Q6, rounding=ROUND_HALF_UP)
    except DecimalException as exc:
        raise MetricCalculationError(
            f"{label} cannot be represented as Numeric(18,6)"
        ) from exc
    if not quantized.is_finite():
        raise MetricCalculationError(
            f"{label} cannot be represented as Numeric(18,6)"
        )
    if abs(quantized) > _NUMERIC_18_6_MAX:
        raise MetricCalculationError(
            f"{label} is outside the Numeric(18,6) range"
        )
    # Avoid persisting or serializing a surprising signed zero.
    return Decimal("0.000000") if quantized == 0 else quantized


def _decimal_string(value: Decimal | None, label: str) -> str | None:
    stored = _stored_decimal(value, label)
    return format(stored, "f") if stored is not None else None


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, _ZERO) / Decimal(len(values))


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        # Strategy CSV timestamps are persisted as naive UTC.
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _exit_order(trade: MetricTrade) -> tuple[int, datetime, int]:
    if trade.exit_at is None:
        return (1, datetime.max, trade.trade_number)
    return (0, _utc_naive(trade.exit_at), trade.trade_number)


def _source_local(value: datetime, source_zone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(source_zone)


def _time_bucket(trade: MetricTrade, source_zone: ZoneInfo) -> str:
    if trade.entry_at is None:
        return "unknown"
    local_time = _source_local(trade.entry_at, source_zone).time().replace(tzinfo=None)
    if local_time < time(9, 30):
        return "premarket"
    if local_time < time(10, 0):
        return "open"
    if local_time < time(14, 0):
        return "mid"
    if local_time < time(16, 0):
        return "close"
    return "afterhours"


def _outcome_values(trades: list[MetricTrade]) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    covered = [trade.net_pnl for trade in trades if trade.net_pnl is not None]
    winners = [value for value in covered if value > 0]
    losers = [value for value in covered if value < 0]
    return covered, winners, losers


def _summary(trades: list[MetricTrade], label: str) -> dict[str, Any]:
    covered, winners, losers = _outcome_values(trades)
    breakeven = len(covered) - len(winners) - len(losers)
    gross_profit = sum(winners, _ZERO)
    gross_loss = sum(losers, _ZERO)
    average_winner = _mean(winners)
    average_loser = _mean(losers)
    payoff_ratio = (
        average_winner / abs(average_loser)
        if average_winner is not None and average_loser is not None
        else None
    )
    returns = [trade.return_pct for trade in trades if trade.return_pct is not None]
    complete = bool(trades) and len(covered) == len(trades)

    def text(value: Decimal | None, field: str) -> str | None:
        return _decimal_string(value, f"{label}.{field}")

    return {
        "trade_count": len(trades),
        "pnl_covered_count": len(covered),
        "pnl_missing_count": len(trades) - len(covered),
        "return_pct_covered_count": len(returns),
        "wins": len(winners),
        "losses": len(losers),
        "breakeven": breakeven,
        "win_rate": text(
            Decimal(len(winners)) / Decimal(len(covered)) if covered else None,
            "win_rate",
        ),
        "average_winner": text(average_winner, "average_winner"),
        "average_loser": text(average_loser, "average_loser"),
        "payoff_ratio": text(payoff_ratio, "payoff_ratio"),
        "total_pnl": text(sum(covered, _ZERO) if complete else None, "total_pnl"),
        "expectancy": text(_mean(covered), "expectancy"),
        "profit_factor": text(
            gross_profit / abs(gross_loss) if gross_loss != 0 else None,
            "profit_factor",
        ),
        "average_return_pct": text(_mean(returns), "average_return_pct"),
    }


def _validate_inputs(trades: list[MetricTrade], initial_capital: Decimal | None) -> None:
    _validate_decimal(initial_capital, "initial_capital")
    if initial_capital is not None:
        _stored_decimal(initial_capital, "initial_capital")
    for index, trade in enumerate(trades):
        prefix = f"trades[{index}]"
        if not isinstance(trade, MetricTrade):
            raise MetricCalculationError(f"{prefix} must be a MetricTrade")
        if not isinstance(trade.trade_number, int) or isinstance(trade.trade_number, bool):
            raise MetricCalculationError(f"{prefix}.trade_number must be an integer")
        if trade.direction not in {"long", "short"}:
            raise MetricCalculationError(f"{prefix}.direction must be long or short")
        if trade.entry_at is not None and not isinstance(trade.entry_at, datetime):
            raise MetricCalculationError(f"{prefix}.entry_at must be a datetime or None")
        if trade.exit_at is not None and not isinstance(trade.exit_at, datetime):
            raise MetricCalculationError(f"{prefix}.exit_at must be a datetime or None")
        for field in ("net_pnl", "return_pct", "mfe", "mae", "cumulative_return_pct"):
            value = getattr(trade, field)
            _validate_decimal(value, f"{prefix}.{field}")
            if value is not None:
                _stored_decimal(value, f"{prefix}.{field}")
        if trade.duration_minutes is not None and (
            not isinstance(trade.duration_minutes, int)
            or isinstance(trade.duration_minutes, bool)
        ):
            raise MetricCalculationError(
                f"{prefix}.duration_minutes must be an integer or None"
            )


def _curves(
    ordered: list[MetricTrade],
    initial_capital: Decimal | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Decimal, Decimal | None]:
    use_initial = initial_capital is not None and initial_capital > 0
    starting_equity = initial_capital if use_initial else _ZERO
    cumulative = _ZERO
    peak_equity = starting_equity
    max_drawdown = _ZERO
    max_drawdown_pct = _ZERO if use_initial else None

    equity_curve: list[dict[str, Any]] = [
        {
            "sequence": 0,
            "trade_number": None,
            "exit_at": None,
            "net_pnl": None,
            "cumulative_net_pnl": _decimal_string(_ZERO, "equity_curve[0].cumulative_net_pnl"),
            "equity": _decimal_string(starting_equity, "equity_curve[0].equity"),
        }
    ]
    drawdown_curve: list[dict[str, Any]] = [
        {
            "sequence": 0,
            "trade_number": None,
            "exit_at": None,
            "peak_equity": _decimal_string(peak_equity, "drawdown_curve[0].peak_equity"),
            "drawdown": _decimal_string(_ZERO, "drawdown_curve[0].drawdown"),
            "drawdown_pct": (
                _decimal_string(_ZERO, "drawdown_curve[0].drawdown_pct")
                if use_initial
                else None
            ),
        }
    ]

    for sequence, trade in enumerate(ordered, start=1):
        # Completeness is checked by the caller before this helper runs.
        assert trade.net_pnl is not None and trade.exit_at is not None
        cumulative += trade.net_pnl
        equity = starting_equity + cumulative
        peak_equity = max(peak_equity, equity)
        drawdown = peak_equity - equity
        max_drawdown = max(max_drawdown, drawdown)
        drawdown_pct = (
            drawdown / peak_equity * _ONE_HUNDRED if use_initial else None
        )
        if drawdown_pct is not None:
            max_drawdown_pct = max(max_drawdown_pct or _ZERO, drawdown_pct)
        exit_at = trade.exit_at.isoformat()
        equity_curve.append(
            {
                "sequence": sequence,
                "trade_number": trade.trade_number,
                "exit_at": exit_at,
                "net_pnl": _decimal_string(trade.net_pnl, f"equity_curve[{sequence}].net_pnl"),
                "cumulative_net_pnl": _decimal_string(
                    cumulative, f"equity_curve[{sequence}].cumulative_net_pnl"
                ),
                "equity": _decimal_string(equity, f"equity_curve[{sequence}].equity"),
            }
        )
        drawdown_curve.append(
            {
                "sequence": sequence,
                "trade_number": trade.trade_number,
                "exit_at": exit_at,
                "peak_equity": _decimal_string(
                    peak_equity, f"drawdown_curve[{sequence}].peak_equity"
                ),
                "drawdown": _decimal_string(
                    drawdown, f"drawdown_curve[{sequence}].drawdown"
                ),
                "drawdown_pct": _decimal_string(
                    drawdown_pct, f"drawdown_curve[{sequence}].drawdown_pct"
                ),
            }
        )
    return equity_curve, drawdown_curve, max_drawdown, max_drawdown_pct


def _calculate_run_metrics(
    trades: Iterable[MetricTrade],
    *,
    initial_capital: Decimal | None,
    source_timezone: str,
) -> RunMetricResult:
    """Calculate one Strategy Lab run using Decimal arithmetic only."""
    try:
        zone_name = source_timezone.strip()
        source_zone = ZoneInfo(zone_name)
    except (AttributeError, OSError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise MetricCalculationError(f"Invalid IANA source timezone: {source_timezone!r}") from exc

    items = list(trades)
    with localcontext() as context:
        # Do not inherit caller-enabled Decimal traps. All arithmetic failures
        # are normalized below into MetricCalculationError instead.
        for signal in context.traps:
            context.traps[signal] = False
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        _validate_inputs(items, initial_capital)

        covered, winners, losers = _outcome_values(items)
        breakeven = len(covered) - len(winners) - len(losers)
        gross_profit = sum(winners, _ZERO)
        gross_loss = sum(losers, _ZERO)
        average_winner_raw = _mean(winners)
        average_loser_raw = _mean(losers)
        payoff_raw = (
            average_winner_raw / abs(average_loser_raw)
            if average_winner_raw is not None and average_loser_raw is not None
            else None
        )

        trade_count = len(items)
        accounting_complete = trade_count > 0 and len(covered) == trade_count
        exit_count = sum(trade.exit_at is not None for trade in items)
        chronology_complete = trade_count > 0 and exit_count == trade_count
        total_raw = sum(covered, _ZERO) if accounting_complete else None

        ordered = sorted(items, key=_exit_order)
        if accounting_complete and chronology_complete:
            equity_curve, drawdown_curve, max_dd_raw, max_dd_pct_raw = _curves(
                ordered, initial_capital
            )
        else:
            equity_curve = []
            drawdown_curve = []
            max_dd_raw = None
            max_dd_pct_raw = None

        positive_initial = initial_capital is not None and initial_capital > 0
        fallback_candidates = [
            trade
            for trade in ordered
            if trade.exit_at is not None and trade.cumulative_return_pct is not None
        ]
        fallback_trade = fallback_candidates[-1] if fallback_candidates else None
        if accounting_complete and positive_initial:
            assert total_raw is not None and initial_capital is not None
            net_return_raw = total_raw / initial_capital * _ONE_HUNDRED
            net_return_basis = "total_net_pnl_over_initial_capital"
        elif fallback_trade is not None:
            net_return_raw = fallback_trade.cumulative_return_pct
            net_return_basis = "source_cumulative_return_pct"
        else:
            net_return_raw = None
            net_return_basis = "unavailable"

        mfe_values = [trade.mfe for trade in items if trade.mfe is not None]
        mae_values = [trade.mae for trade in items if trade.mae is not None]
        valid_durations = [
            Decimal(trade.duration_minutes)
            for trade in items
            if trade.duration_minutes is not None and trade.duration_minutes >= 0
        ]
        invalid_durations = sum(
            trade.duration_minutes is not None and trade.duration_minutes < 0
            for trade in items
        )

        positive_total = total_raw is not None and total_raw > 0

        def top_contribution(count: int) -> Decimal | None:
            if not positive_total:
                return None
            assert total_raw is not None
            return sum(sorted(winners, reverse=True)[:count], _ZERO) / total_raw * _ONE_HUNDRED

        long_trades = [trade for trade in items if trade.direction == "long"]
        short_trades = [trade for trade in items if trade.direction == "short"]
        bucketed: dict[str, list[MetricTrade]] = {name: [] for name in _TIME_BUCKETS}
        for trade in items:
            bucketed[_time_bucket(trade, source_zone)].append(trade)

        average_winner = _stored_decimal(average_winner_raw, "average_winner")
        average_loser = _stored_decimal(average_loser_raw, "average_loser")
        payoff_ratio = _stored_decimal(payoff_raw, "payoff_ratio")
        expectancy = _stored_decimal(_mean(covered), "expectancy")
        profit_factor = _stored_decimal(
            gross_profit / abs(gross_loss) if gross_loss != 0 else None,
            "profit_factor",
        )
        total_net_pnl = _stored_decimal(total_raw, "total_net_pnl")
        net_return_pct = _stored_decimal(net_return_raw, "net_return_pct")
        max_drawdown = _stored_decimal(max_dd_raw, "max_drawdown")
        max_drawdown_pct = _stored_decimal(max_dd_pct_raw, "max_drawdown_pct")
        average_mfe = _stored_decimal(_mean(mfe_values), "average_mfe")
        median_mfe = _stored_decimal(_median(mfe_values), "median_mfe")
        average_mae = _stored_decimal(_mean(mae_values), "average_mae")
        median_mae = _stored_decimal(_median(mae_values), "median_mae")
        average_holding = _stored_decimal(
            _mean(valid_durations), "average_holding_minutes"
        )
        top_1 = _stored_decimal(top_contribution(1), "top_1_profit_contribution_pct")
        top_3 = _stored_decimal(top_contribution(3), "top_3_profit_contribution_pct")
        top_5 = _stored_decimal(top_contribution(5), "top_5_profit_contribution_pct")
        win_rate = _stored_decimal(
            Decimal(len(winners)) / Decimal(len(covered)) if covered else None,
            "win_rate",
        )

        undefined: dict[str, str] = {}
        scalar_values = {
            "win_rate": win_rate,
            "average_winner": average_winner,
            "average_loser": average_loser,
            "payoff_ratio": payoff_ratio,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "total_net_pnl": total_net_pnl,
            "net_return_pct": net_return_pct,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "average_mfe": average_mfe,
            "median_mfe": median_mfe,
            "average_mae": average_mae,
            "median_mae": median_mae,
            "average_holding_minutes": average_holding,
            "top_1_profit_contribution_pct": top_1,
            "top_3_profit_contribution_pct": top_3,
            "top_5_profit_contribution_pct": top_5,
        }
        for field, value in scalar_values.items():
            if value is not None:
                continue
            if field in {"total_net_pnl", "top_1_profit_contribution_pct", "top_3_profit_contribution_pct", "top_5_profit_contribution_pct"}:
                reason = "incomplete_net_pnl" if trade_count and not accounting_complete else "no_positive_total_net_pnl"
            elif field in {"max_drawdown", "max_drawdown_pct"}:
                if not accounting_complete:
                    reason = "incomplete_net_pnl"
                elif not chronology_complete:
                    reason = "incomplete_exit_chronology"
                else:
                    reason = "positive_initial_capital_required"
            elif field == "net_return_pct":
                reason = "initial_capital_or_source_cumulative_return_pct_unavailable"
            elif field in {"average_winner"}:
                reason = "no_winning_trades"
            elif field in {"average_loser", "profit_factor"}:
                reason = "no_losing_trades"
            elif field == "payoff_ratio":
                reason = "winning_and_losing_trades_required"
            else:
                reason = "no_covered_values"
            undefined[field] = reason

        field_coverage = {
            "net_pnl": {"available": len(covered), "missing": trade_count - len(covered)},
            "return_pct": {
                "available": sum(trade.return_pct is not None for trade in items),
                "missing": sum(trade.return_pct is None for trade in items),
            },
            "mfe": {"available": len(mfe_values), "missing": trade_count - len(mfe_values)},
            "mae": {"available": len(mae_values), "missing": trade_count - len(mae_values)},
            "duration_minutes": {
                "available": len(valid_durations),
                "missing": sum(trade.duration_minutes is None for trade in items),
                "invalid": invalid_durations,
            },
            "entry_at": {
                "available": sum(trade.entry_at is not None for trade in items),
                "missing": sum(trade.entry_at is None for trade in items),
            },
            "exit_at": {"available": exit_count, "missing": trade_count - exit_count},
            "cumulative_return_pct": {
                "available": sum(trade.cumulative_return_pct is not None for trade in items),
                "missing": sum(trade.cumulative_return_pct is None for trade in items),
                "chronologically_usable": len(fallback_candidates),
            },
        }
        coverage = {
            "schema_version": 1,
            "total_trades": trade_count,
            "fields": field_coverage,
            "outcomes": {
                "wins": len(winners),
                "losses": len(losers),
                "breakeven": breakeven,
            },
            "denominators": {
                "win_rate_count": len(covered),
                "average_winner_count": len(winners),
                "average_loser_count": len(losers),
                "expectancy_count": len(covered),
                "profit_factor_absolute_gross_loss": _decimal_string(
                    abs(gross_loss) if gross_loss != 0 else None,
                    "coverage.denominators.profit_factor_absolute_gross_loss",
                ),
                "average_mfe_count": len(mfe_values),
                "median_mfe_count": len(mfe_values),
                "average_mae_count": len(mae_values),
                "median_mae_count": len(mae_values),
                "average_holding_minutes_count": len(valid_durations),
                "top_profit_contribution_total_net_pnl": _decimal_string(
                    total_raw if positive_total else None,
                    "coverage.denominators.top_profit_contribution_total_net_pnl",
                ),
            },
            "initial_capital": {
                "value": _decimal_string(initial_capital, "coverage.initial_capital.value"),
                "usable_for_percent": positive_initial,
            },
            "accounting_complete": accounting_complete,
            "chronology_complete": chronology_complete,
            "net_return_basis": net_return_basis,
            "net_return_fallback_trade_number": (
                fallback_trade.trade_number if net_return_basis == "source_cumulative_return_pct" else None
            ),
            "max_drawdown_basis": (
                "equity_peak_to_trough_from_initial_or_zero"
                if accounting_complete and chronology_complete
                else "unavailable"
            ),
            "max_drawdown_pct_basis": (
                "drawdown_over_peak_equity"
                if accounting_complete and chronology_complete and positive_initial
                else "unavailable"
            ),
            "top_profit_contribution_basis": "positive_winners_over_positive_total_net_pnl",
            "source_timezone": zone_name,
            "equity_order": ["exit_at", "trade_number"],
            "undefined_metrics": undefined,
        }

        return RunMetricResult(
            calculation_version=CALCULATION_VERSION,
            trade_count=trade_count,
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=win_rate,
            average_winner=average_winner,
            average_loser=average_loser,
            payoff_ratio=payoff_ratio,
            expectancy=expectancy,
            profit_factor=profit_factor,
            total_net_pnl=total_net_pnl,
            net_return_pct=net_return_pct,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            average_mfe=average_mfe,
            median_mfe=median_mfe,
            average_mae=average_mae,
            median_mae=median_mae,
            average_holding_minutes=average_holding,
            top_1_profit_contribution_pct=top_1,
            top_3_profit_contribution_pct=top_3,
            top_5_profit_contribution_pct=top_5,
            long_summary=_summary(long_trades, "long_summary"),
            short_summary=_summary(short_trades, "short_summary"),
            time_bucket_summary={
                name: _summary(bucketed[name], f"time_bucket_summary.{name}")
                for name in _TIME_BUCKETS
            },
            coverage=coverage,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            findings=[],
        )


def calculate_run_metrics(
    trades: Iterable[MetricTrade],
    *,
    initial_capital: Decimal | None,
    source_timezone: str,
) -> RunMetricResult:
    """Calculate one run without inheriting caller Decimal failure modes."""
    try:
        return _calculate_run_metrics(
            trades,
            initial_capital=initial_capital,
            source_timezone=source_timezone,
        )
    except MetricCalculationError:
        raise
    except DecimalException as exc:
        raise MetricCalculationError("Decimal metric calculation failed") from exc
