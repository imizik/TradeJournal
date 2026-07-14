from __future__ import annotations

from datetime import datetime
from decimal import Decimal, Inexact, localcontext

import pytest

from app.engine.strategy_metrics import (
    CALCULATION_VERSION,
    MetricCalculationError,
    MetricTrade,
    calculate_run_metrics,
)


def _trade(
    trade_number: int,
    *,
    direction: str = "long",
    entry_at: datetime | None = None,
    exit_at: datetime | None = None,
    net_pnl: str | None = "0",
    return_pct: str | None = "0",
    mfe: str | None = "0",
    mae: str | None = "0",
    duration_minutes: int | None = 1,
    cumulative_return_pct: str | None = None,
) -> MetricTrade:
    return MetricTrade(
        trade_number=trade_number,
        direction=direction,
        entry_at=entry_at,
        exit_at=exit_at,
        net_pnl=Decimal(net_pnl) if net_pnl is not None else None,
        return_pct=Decimal(return_pct) if return_pct is not None else None,
        mfe=Decimal(mfe) if mfe is not None else None,
        mae=Decimal(mae) if mae is not None else None,
        duration_minutes=duration_minutes,
        cumulative_return_pct=(
            Decimal(cumulative_return_pct)
            if cumulative_return_pct is not None
            else None
        ),
    )


def _mixed_trades() -> list[MetricTrade]:
    """Seven invented trades, with one entry in every New York time bucket."""
    return [
        _trade(
            1,
            entry_at=datetime(2026, 1, 5, 13, 0),  # 08:00 ET: premarket
            exit_at=datetime(2026, 1, 5, 13, 20),
            net_pnl="100",
            return_pct="10",
            mfe="10",
            mae="-10",
            duration_minutes=10,
            cumulative_return_pct="10",
        ),
        _trade(
            2,
            direction="short",
            entry_at=datetime(2026, 1, 6, 14, 45),  # 09:45 ET: open
            exit_at=datetime(2026, 1, 6, 15, 5),
            net_pnl="-50",
            return_pct="-5",
            mfe="20",
            mae="-20",
            duration_minutes=20,
            cumulative_return_pct="5",
        ),
        _trade(
            3,
            entry_at=datetime(2026, 1, 7, 16, 0),  # 11:00 ET: mid
            exit_at=datetime(2026, 1, 7, 16, 30),
            net_pnl="200",
            return_pct="20",
            mfe="30",
            mae="-30",
            duration_minutes=30,
            cumulative_return_pct="25",
        ),
        _trade(
            4,
            direction="short",
            entry_at=datetime(2026, 1, 8, 20, 15),  # 15:15 ET: close
            exit_at=datetime(2026, 1, 8, 20, 55),
            net_pnl="-100",
            return_pct="-10",
            mfe="40",
            mae="-40",
            duration_minutes=40,
            cumulative_return_pct="15",
        ),
        _trade(
            5,
            entry_at=datetime(2026, 1, 9, 21, 15),  # 16:15 ET: afterhours
            exit_at=datetime(2026, 1, 9, 21, 45),
            net_pnl="0",
            return_pct="0",
            mfe="50",
            mae="-50",
            duration_minutes=50,
            cumulative_return_pct="15",
        ),
        _trade(
            6,
            direction="short",
            entry_at=datetime(2026, 1, 10, 15, 0),  # 10:00 ET: mid boundary
            exit_at=datetime(2026, 1, 10, 15, 45),
            net_pnl="50",
            return_pct="5",
            mfe="60",
            mae="-60",
            duration_minutes=60,
            cumulative_return_pct="20",
        ),
        _trade(
            7,
            entry_at=datetime(2026, 1, 11, 19, 0),  # 14:00 ET: close boundary
            exit_at=datetime(2026, 1, 11, 20, 20),
            net_pnl="-25",
            return_pct="-2.5",
            mfe="70",
            mae="-70",
            duration_minutes=70,
            cumulative_return_pct="17.5",
        ),
    ]


def _summary(
    *,
    trade_count: int,
    wins: int,
    losses: int,
    breakevens: int,
    win_rate: str | None,
    average_winner: str | None,
    average_loser: str | None,
    payoff_ratio: str | None,
    expectancy: str | None,
    profit_factor: str | None,
    total_net_pnl: str | None,
    average_return_pct: str | None,
    missing: int = 0,
) -> dict[str, object]:
    return {
        "trade_count": trade_count,
        "pnl_covered_count": trade_count - missing,
        "pnl_missing_count": missing,
        "return_pct_covered_count": trade_count - missing,
        "wins": wins,
        "losses": losses,
        "breakeven": breakevens,
        "win_rate": win_rate,
        "average_winner": average_winner,
        "average_loser": average_loser,
        "payoff_ratio": payoff_ratio,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "total_pnl": total_net_pnl,
        "average_return_pct": average_return_pct,
    }


def test_mixed_run_calculates_every_scalar_and_chronological_curves() -> None:
    result = calculate_run_metrics(
        list(reversed(_mixed_trades())),
        initial_capital=Decimal("1000"),
        source_timezone="America/New_York",
    )

    assert result.calculation_version == CALCULATION_VERSION
    assert result.trade_count == 7
    assert result.winning_trades == 3
    assert result.losing_trades == 3
    assert result.win_rate == Decimal("0.428571")
    assert result.average_winner == Decimal("116.666667")
    assert result.average_loser == Decimal("-58.333333")
    assert result.payoff_ratio == Decimal("2.000000")
    assert result.expectancy == Decimal("25.000000")
    assert result.profit_factor == Decimal("2.000000")
    assert result.total_net_pnl == Decimal("175.000000")
    assert result.net_return_pct == Decimal("17.500000")
    assert result.max_drawdown == Decimal("100.000000")
    assert result.max_drawdown_pct == Decimal("8.000000")
    assert result.average_mfe == Decimal("40.000000")
    assert result.median_mfe == Decimal("40.000000")
    assert result.average_mae == Decimal("-40.000000")
    assert result.median_mae == Decimal("-40.000000")
    assert result.average_holding_minutes == Decimal("40.000000")
    # Concentration intentionally uses positive total net PnL as its denominator,
    # so values above 100% are possible when winners offset losing trades.
    assert result.top_1_profit_contribution_pct == Decimal("114.285714")
    assert result.top_3_profit_contribution_pct == Decimal("200.000000")
    assert result.top_5_profit_contribution_pct == Decimal("200.000000")

    assert result.long_summary == _summary(
        trade_count=4,
        wins=2,
        losses=1,
        breakevens=1,
        win_rate="0.500000",
        average_winner="150.000000",
        average_loser="-25.000000",
        payoff_ratio="6.000000",
        expectancy="68.750000",
        profit_factor="12.000000",
        total_net_pnl="275.000000",
        average_return_pct="6.875000",
    )
    assert result.short_summary == _summary(
        trade_count=3,
        wins=1,
        losses=2,
        breakevens=0,
        win_rate="0.333333",
        average_winner="50.000000",
        average_loser="-75.000000",
        payoff_ratio="0.666667",
        expectancy="-33.333333",
        profit_factor="0.333333",
        total_net_pnl="-100.000000",
        average_return_pct="-3.333333",
    )
    assert result.time_bucket_summary == {
        "premarket": _summary(
            trade_count=1,
            wins=1,
            losses=0,
            breakevens=0,
            win_rate="1.000000",
            average_winner="100.000000",
            average_loser=None,
            payoff_ratio=None,
            expectancy="100.000000",
            profit_factor=None,
            total_net_pnl="100.000000",
            average_return_pct="10.000000",
        ),
        "open": _summary(
            trade_count=1,
            wins=0,
            losses=1,
            breakevens=0,
            win_rate="0.000000",
            average_winner=None,
            average_loser="-50.000000",
            payoff_ratio=None,
            expectancy="-50.000000",
            profit_factor="0.000000",
            total_net_pnl="-50.000000",
            average_return_pct="-5.000000",
        ),
        "mid": _summary(
            trade_count=2,
            wins=2,
            losses=0,
            breakevens=0,
            win_rate="1.000000",
            average_winner="125.000000",
            average_loser=None,
            payoff_ratio=None,
            expectancy="125.000000",
            profit_factor=None,
            total_net_pnl="250.000000",
            average_return_pct="12.500000",
        ),
        "close": _summary(
            trade_count=2,
            wins=0,
            losses=2,
            breakevens=0,
            win_rate="0.000000",
            average_winner=None,
            average_loser="-62.500000",
            payoff_ratio=None,
            expectancy="-62.500000",
            profit_factor="0.000000",
            total_net_pnl="-125.000000",
            average_return_pct="-6.250000",
        ),
        "afterhours": _summary(
            trade_count=1,
            wins=0,
            losses=0,
            breakevens=1,
            win_rate="0.000000",
            average_winner=None,
            average_loser=None,
            payoff_ratio=None,
            expectancy="0.000000",
            profit_factor=None,
            total_net_pnl="0.000000",
            average_return_pct="0.000000",
        ),
        "unknown": _summary(
            trade_count=0,
            wins=0,
            losses=0,
            breakevens=0,
            win_rate=None,
            average_winner=None,
            average_loser=None,
            payoff_ratio=None,
            expectancy=None,
            profit_factor=None,
            total_net_pnl=None,
            average_return_pct=None,
        ),
    }

    assert result.coverage["schema_version"] == 1
    assert result.coverage["total_trades"] == 7
    assert result.coverage["outcomes"] == {
        "wins": 3,
        "losses": 3,
        "breakeven": 1,
    }
    assert result.coverage["initial_capital"] == {
        "value": "1000.000000",
        "usable_for_percent": True,
    }
    assert result.coverage["accounting_complete"] is True
    assert result.coverage["chronology_complete"] is True
    assert result.coverage["source_timezone"] == "America/New_York"
    assert result.coverage["undefined_metrics"] == {}

    assert result.equity_curve == [
        {
            "sequence": 0,
            "trade_number": None,
            "exit_at": None,
            "net_pnl": None,
            "cumulative_net_pnl": "0.000000",
            "equity": "1000.000000",
        },
        {
            "sequence": 1,
            "trade_number": 1,
            "exit_at": "2026-01-05T13:20:00",
            "net_pnl": "100.000000",
            "cumulative_net_pnl": "100.000000",
            "equity": "1100.000000",
        },
        {
            "sequence": 2,
            "trade_number": 2,
            "exit_at": "2026-01-06T15:05:00",
            "net_pnl": "-50.000000",
            "cumulative_net_pnl": "50.000000",
            "equity": "1050.000000",
        },
        {
            "sequence": 3,
            "trade_number": 3,
            "exit_at": "2026-01-07T16:30:00",
            "net_pnl": "200.000000",
            "cumulative_net_pnl": "250.000000",
            "equity": "1250.000000",
        },
        {
            "sequence": 4,
            "trade_number": 4,
            "exit_at": "2026-01-08T20:55:00",
            "net_pnl": "-100.000000",
            "cumulative_net_pnl": "150.000000",
            "equity": "1150.000000",
        },
        {
            "sequence": 5,
            "trade_number": 5,
            "exit_at": "2026-01-09T21:45:00",
            "net_pnl": "0.000000",
            "cumulative_net_pnl": "150.000000",
            "equity": "1150.000000",
        },
        {
            "sequence": 6,
            "trade_number": 6,
            "exit_at": "2026-01-10T15:45:00",
            "net_pnl": "50.000000",
            "cumulative_net_pnl": "200.000000",
            "equity": "1200.000000",
        },
        {
            "sequence": 7,
            "trade_number": 7,
            "exit_at": "2026-01-11T20:20:00",
            "net_pnl": "-25.000000",
            "cumulative_net_pnl": "175.000000",
            "equity": "1175.000000",
        },
    ]
    assert result.drawdown_curve == [
        {
            "sequence": 0,
            "trade_number": None,
            "exit_at": None,
            "peak_equity": "1000.000000",
            "drawdown": "0.000000",
            "drawdown_pct": "0.000000",
        },
        {
            "sequence": 1,
            "trade_number": 1,
            "exit_at": "2026-01-05T13:20:00",
            "peak_equity": "1100.000000",
            "drawdown": "0.000000",
            "drawdown_pct": "0.000000",
        },
        {
            "sequence": 2,
            "trade_number": 2,
            "exit_at": "2026-01-06T15:05:00",
            "peak_equity": "1100.000000",
            "drawdown": "50.000000",
            "drawdown_pct": "4.545455",
        },
        {
            "sequence": 3,
            "trade_number": 3,
            "exit_at": "2026-01-07T16:30:00",
            "peak_equity": "1250.000000",
            "drawdown": "0.000000",
            "drawdown_pct": "0.000000",
        },
        {
            "sequence": 4,
            "trade_number": 4,
            "exit_at": "2026-01-08T20:55:00",
            "peak_equity": "1250.000000",
            "drawdown": "100.000000",
            "drawdown_pct": "8.000000",
        },
        {
            "sequence": 5,
            "trade_number": 5,
            "exit_at": "2026-01-09T21:45:00",
            "peak_equity": "1250.000000",
            "drawdown": "100.000000",
            "drawdown_pct": "8.000000",
        },
        {
            "sequence": 6,
            "trade_number": 6,
            "exit_at": "2026-01-10T15:45:00",
            "peak_equity": "1250.000000",
            "drawdown": "50.000000",
            "drawdown_pct": "4.000000",
        },
        {
            "sequence": 7,
            "trade_number": 7,
            "exit_at": "2026-01-11T20:20:00",
            "peak_equity": "1250.000000",
            "drawdown": "75.000000",
            "drawdown_pct": "6.000000",
        },
    ]


def test_missing_fields_are_reported_and_source_cumulative_return_is_fallback() -> None:
    trades = [
        _trade(
            1,
            entry_at=datetime(2026, 2, 2, 14, 30),
            exit_at=datetime(2026, 2, 2, 14, 35),
            net_pnl="10",
            return_pct="1",
            mfe="5",
            mae="-2",
            duration_minutes=5,
            cumulative_return_pct="1",
        ),
        _trade(
            2,
            entry_at=None,
            exit_at=datetime(2026, 2, 3, 14, 35),
            net_pnl=None,
            return_pct=None,
            mfe=None,
            mae="-4",
            duration_minutes=None,
            cumulative_return_pct="2.5",
        ),
        _trade(
            3,
            entry_at=datetime(2026, 2, 4, 14, 30),
            exit_at=datetime(2026, 2, 4, 14, 35),
            net_pnl="-5",
            return_pct="-0.5",
            mfe="1",
            mae=None,
            duration_minutes=-3,
            cumulative_return_pct=None,
        ),
    ]

    result = calculate_run_metrics(
        trades,
        initial_capital=None,
        source_timezone="America/New_York",
    )

    # Outcome-quality metrics may use known PnL, but accounting aggregates must
    # not silently present a partial run as complete.
    assert result.trade_count == 3
    assert result.winning_trades == 1
    assert result.losing_trades == 1
    assert result.win_rate == Decimal("0.500000")
    assert result.average_winner == Decimal("10.000000")
    assert result.average_loser == Decimal("-5.000000")
    assert result.payoff_ratio == Decimal("2.000000")
    assert result.expectancy == Decimal("2.500000")
    assert result.profit_factor == Decimal("2.000000")
    assert result.total_net_pnl is None
    assert result.net_return_pct == Decimal("2.500000")
    assert result.max_drawdown is None
    assert result.max_drawdown_pct is None
    assert result.top_1_profit_contribution_pct is None
    assert result.top_3_profit_contribution_pct is None
    assert result.top_5_profit_contribution_pct is None
    assert result.equity_curve == []
    assert result.drawdown_curve == []
    assert result.average_mfe == Decimal("3.000000")
    assert result.median_mfe == Decimal("3.000000")
    assert result.average_mae == Decimal("-3.000000")
    assert result.median_mae == Decimal("-3.000000")
    assert result.average_holding_minutes == Decimal("5.000000")

    assert result.coverage["fields"]["net_pnl"] == {
        "available": 2,
        "missing": 1,
    }
    assert result.coverage["fields"]["return_pct"] == {
        "available": 2,
        "missing": 1,
    }
    assert result.coverage["fields"]["mfe"] == {
        "available": 2,
        "missing": 1,
    }
    assert result.coverage["fields"]["mae"] == {
        "available": 2,
        "missing": 1,
    }
    assert result.coverage["fields"]["duration_minutes"] == {
        "available": 1,
        "missing": 1,
        "invalid": 1,
    }
    assert result.coverage["fields"]["entry_at"] == {
        "available": 2,
        "missing": 1,
    }
    assert result.coverage["fields"]["exit_at"] == {
        "available": 3,
        "missing": 0,
    }
    assert result.coverage["outcomes"] == {
        "wins": 1,
        "losses": 1,
        "breakeven": 0,
    }
    assert result.coverage["initial_capital"] == {
        "value": None,
        "usable_for_percent": False,
    }
    assert result.coverage["accounting_complete"] is False
    assert result.coverage["chronology_complete"] is True
    assert result.coverage["net_return_basis"] == "source_cumulative_return_pct"
    assert result.coverage["undefined_metrics"]
    assert result.long_summary["total_pnl"] is None
    assert result.time_bucket_summary["unknown"] == _summary(
        trade_count=1,
        wins=0,
        losses=0,
        breakevens=0,
        win_rate=None,
        average_winner=None,
        average_loser=None,
        payoff_ratio=None,
        expectancy=None,
        profit_factor=None,
        total_net_pnl=None,
        average_return_pct=None,
        missing=1,
    )


def test_complete_pnl_with_incomplete_exit_chronology_withholds_curves() -> None:
    result = calculate_run_metrics(
        [
            _trade(
                1,
                exit_at=datetime(2026, 2, 1, 15, 0),
                net_pnl="10",
            ),
            _trade(2, exit_at=None, net_pnl="-5"),
        ],
        initial_capital=Decimal("100"),
        source_timezone="UTC",
    )

    assert result.total_net_pnl == Decimal("5.000000")
    assert result.net_return_pct == Decimal("5.000000")
    assert result.coverage["accounting_complete"] is True
    assert result.coverage["chronology_complete"] is False
    assert result.max_drawdown is None
    assert result.max_drawdown_pct is None
    assert result.equity_curve == []
    assert result.drawdown_curve == []
    assert result.coverage["undefined_metrics"]["max_drawdown"] == (
        "incomplete_exit_chronology"
    )


def test_dollar_drawdown_remains_available_without_initial_capital() -> None:
    result = calculate_run_metrics(
        [
            _trade(
                1,
                exit_at=datetime(2026, 2, 1, 15, 0),
                net_pnl="10",
                cumulative_return_pct=None,
            ),
            _trade(
                2,
                exit_at=datetime(2026, 2, 2, 15, 0),
                net_pnl="-20",
                cumulative_return_pct=None,
            ),
        ],
        initial_capital=None,
        source_timezone="UTC",
    )

    assert result.total_net_pnl == Decimal("-10.000000")
    assert result.net_return_pct is None
    assert result.max_drawdown == Decimal("20.000000")
    assert result.max_drawdown_pct is None
    assert result.equity_curve[0]["equity"] == "0.000000"
    assert result.drawdown_curve[-1]["drawdown"] == "20.000000"
    assert result.drawdown_curve[-1]["drawdown_pct"] is None


@pytest.mark.parametrize(
    ("pnls", "expected"),
    [
        (
            ["10", "20"],
            {
                "winning_trades": 2,
                "losing_trades": 0,
                "win_rate": Decimal("1.000000"),
                "average_winner": Decimal("15.000000"),
                "average_loser": None,
                "payoff_ratio": None,
                "expectancy": Decimal("15.000000"),
                "profit_factor": None,
                "total_net_pnl": Decimal("30.000000"),
                "top_1": Decimal("66.666667"),
            },
        ),
        (
            ["-10", "-20"],
            {
                "winning_trades": 0,
                "losing_trades": 2,
                "win_rate": Decimal("0.000000"),
                "average_winner": None,
                "average_loser": Decimal("-15.000000"),
                "payoff_ratio": None,
                "expectancy": Decimal("-15.000000"),
                "profit_factor": Decimal("0.000000"),
                "total_net_pnl": Decimal("-30.000000"),
                "top_1": None,
            },
        ),
        (
            ["0", "0"],
            {
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": Decimal("0.000000"),
                "average_winner": None,
                "average_loser": None,
                "payoff_ratio": None,
                "expectancy": Decimal("0.000000"),
                "profit_factor": None,
                "total_net_pnl": Decimal("0.000000"),
                "top_1": None,
            },
        ),
        (
            [None, None],
            {
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": None,
                "average_winner": None,
                "average_loser": None,
                "payoff_ratio": None,
                "expectancy": None,
                "profit_factor": None,
                "total_net_pnl": None,
                "top_1": None,
            },
        ),
    ],
    ids=["all-winners", "all-losers", "all-breakeven", "no-pnl"],
)
def test_outcome_only_runs_have_explicit_undefined_metrics(
    pnls: list[str | None],
    expected: dict[str, object],
) -> None:
    trades = [
        _trade(
            number,
            entry_at=datetime(2026, 3, number, 15, 0),
            exit_at=datetime(2026, 3, number, 15, 5),
            net_pnl=pnl,
        )
        for number, pnl in enumerate(pnls, start=1)
    ]

    result = calculate_run_metrics(
        trades,
        initial_capital=Decimal("100"),
        source_timezone="UTC",
    )

    for field in (
        "winning_trades",
        "losing_trades",
        "win_rate",
        "average_winner",
        "average_loser",
        "payoff_ratio",
        "expectancy",
        "profit_factor",
        "total_net_pnl",
    ):
        assert getattr(result, field) == expected[field]
    assert result.top_1_profit_contribution_pct == expected["top_1"]
    if expected["top_1"] is None:
        assert result.top_3_profit_contribution_pct is None
        assert result.top_5_profit_contribution_pct is None

    if pnls == [None, None]:
        assert result.net_return_pct is None
        assert result.max_drawdown is None
        assert result.max_drawdown_pct is None
        assert result.equity_curve == []
        assert result.drawdown_curve == []
        assert result.coverage["accounting_complete"] is False


def test_realized_order_is_stable_for_equal_exit_timestamps() -> None:
    tied = datetime(2026, 4, 1, 15, 0)
    later = datetime(2026, 4, 1, 16, 0)
    trades = [
        _trade(10, exit_at=later, net_pnl="10"),
        _trade(2, exit_at=tied, net_pnl="2"),
        _trade(1, exit_at=tied, net_pnl="1"),
    ]

    first = calculate_run_metrics(
        trades,
        initial_capital=Decimal("100"),
        source_timezone="UTC",
    )
    second = calculate_run_metrics(
        [trades[1], trades[0], trades[2]],
        initial_capital=Decimal("100"),
        source_timezone="UTC",
    )

    assert first == second
    assert [point["trade_number"] for point in first.equity_curve] == [
        None,
        1,
        2,
        10,
    ]
    assert [point["cumulative_net_pnl"] for point in first.equity_curve] == [
        "0.000000",
        "1.000000",
        "3.000000",
        "13.000000",
    ]


def test_invalid_source_timezone_is_a_typed_calculation_error() -> None:
    with pytest.raises(MetricCalculationError, match="timezone"):
        calculate_run_metrics(
            [_trade(1)],
            initial_capital=None,
            source_timezone="Mars/Olympus",
        )


def test_numeric_results_round_half_up_and_overflow_is_rejected() -> None:
    rounded = calculate_run_metrics(
        [_trade(1, net_pnl="0"), _trade(2, net_pnl="0.000001")],
        initial_capital=None,
        source_timezone="UTC",
    )
    assert rounded.expectancy == Decimal("0.000001")

    boundary = calculate_run_metrics(
        [
            _trade(
                1,
                exit_at=datetime(2026, 5, 1, 15, 0),
                net_pnl="999999999999.999999",
            )
        ],
        initial_capital=None,
        source_timezone="UTC",
    )
    assert boundary.total_net_pnl == Decimal("999999999999.999999")

    with pytest.raises(MetricCalculationError):
        calculate_run_metrics(
            [
                _trade(1, net_pnl="999999999999.999999"),
                _trade(2, net_pnl="0.000001"),
            ],
            initial_capital=None,
            source_timezone="UTC",
        )

    with pytest.raises(MetricCalculationError):
        calculate_run_metrics(
            [_trade(1, net_pnl="1e999999")],
            initial_capital=Decimal("1"),
            source_timezone="UTC",
        )


def test_caller_decimal_traps_do_not_change_results() -> None:
    with localcontext() as context:
        context.traps[Inexact] = True
        result = calculate_run_metrics(
            [
                _trade(1, net_pnl="1"),
                _trade(2, net_pnl="2"),
                _trade(3, net_pnl="-1"),
            ],
            initial_capital=None,
            source_timezone="UTC",
        )

    assert result.win_rate == Decimal("0.666667")
    assert result.expectancy == Decimal("0.666667")
