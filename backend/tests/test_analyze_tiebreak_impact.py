from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")


def _load_script(name: str, filename: str):
    path = BACKEND_DIR / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_detects_tie_group_without_inventing_a_pnl_delta(tmp_path) -> None:
    seed_module = _load_script("seed_dev_data_for_tiebreak", "seed_dev_data.py")
    analysis = _load_script("analyze_tiebreak_impact_seed", "analyze_tiebreak_impact.py")
    database_url = f"sqlite:///{tmp_path / 'seed.db'}"
    seed_module.seed(database_url)

    report = analysis.analyze_database(database_url)

    assert report["total_trades"] == 6
    assert report["tie_group_count"] == 1
    assert report["affected_trade_count"] == 1
    assert report["tickers"] == [
        {"ticker": "RNXT", "affected_trades": 1, "closed_or_expired": 1}
    ]
    # Both RNXT entry lots are eventually sold, so their order cannot change
    # the trade's +$135 total. This is a property of the seed fixture, not a
    # reason to manufacture a non-zero result.
    assert {
        candidate["delta_vs_id"]
        for candidate in report["candidates"].values()
    } == {"0.000000"}
    assert "none of the tested orderings changes realized P&L" in report["verdict"]


def test_partial_exit_fixture_reports_nonzero_candidate_delta() -> None:
    analysis = _load_script("analyze_tiebreak_impact_delta", "analyze_tiebreak_impact.py")
    account_id = uuid.UUID(int=100)
    timestamp = datetime(2026, 3, 1, 10, 0, tzinfo=ET)
    fills = [
        analysis.SourceFill(
            id=uuid.UUID(int=1),
            account_id=account_id,
            ticker="TIE",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("10"),
            executed_at=timestamp,
            raw_email_id="b",
        ),
        analysis.SourceFill(
            id=uuid.UUID(int=2),
            account_id=account_id,
            ticker="TIE",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("20"),
            executed_at=timestamp,
            raw_email_id="a",
        ),
        analysis.SourceFill(
            id=uuid.UUID(int=3),
            account_id=account_id,
            ticker="TIE",
            instrument_type="stock",
            side="sell",
            contracts=Decimal("1"),
            price=Decimal("30"),
            executed_at=datetime(2026, 3, 1, 11, 0, tzinfo=ET),
            raw_email_id="c",
        ),
    ]

    report = analysis.analyze_fills(
        fills,
        account_labels={account_id: "Test (...0000)"},
        today=date(2026, 3, 2),
    )

    assert report["affected_trade_count"] == 1
    assert report["candidates"]["id"]["realized_pnl_total"] == "20.000000"
    assert report["candidates"]["raw_email_id"]["delta_vs_id"] == "-10.000000"
    assert report["candidates"]["price_descending"]["delta_vs_id"] == "-10.000000"


def test_dataset_without_tie_groups_reports_no_affected_trades() -> None:
    analysis = _load_script("analyze_tiebreak_impact_none", "analyze_tiebreak_impact.py")
    account_id = uuid.UUID(int=200)
    fills = [
        analysis.SourceFill(
            id=uuid.UUID(int=10),
            account_id=account_id,
            ticker="NONE",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("10"),
            executed_at=datetime(2026, 3, 1, 10, 0, tzinfo=ET),
            raw_email_id="10",
        ),
        analysis.SourceFill(
            id=uuid.UUID(int=11),
            account_id=account_id,
            ticker="NONE",
            instrument_type="stock",
            side="sell",
            contracts=Decimal("1"),
            price=Decimal("12"),
            executed_at=datetime(2026, 3, 1, 11, 0, tzinfo=ET),
            raw_email_id="11",
        ),
    ]

    report = analysis.analyze_fills(fills, today=date(2026, 3, 2))

    assert report["tie_group_count"] == 0
    assert report["affected_trade_count"] == 0
    assert report["affected_trade_share_pct"] == "0.00"
    assert report["candidates"] == {}
    assert "current tie-break can stay" in report["verdict"]
