"""Accounting, coverage and temporal semantics of the read-only explorer."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine.analytics import analyze, summarize
from app.models import Account, Tag, Trade, TradeTag
from app.routers.stats import router

ACCOUNT = UUID(int=1)
OTHER_ACCOUNT = UUID(int=2)


def trade(number, pnl, **overrides):
    values = dict(id=UUID(int=100 + number), account_id=ACCOUNT, ticker="SPY", instrument_type="option",
                  contracts=1, avg_entry_premium=100, total_premium_paid=100,
                  realized_pnl=Decimal(str(pnl)) if pnl is not None else None,
                  pnl_pct=None, opened_at=datetime(2026, 9, 1, 9, 30 + number),
                  closed_at=datetime(2026, 9, 1, 10, number), status="closed")
    values.update(overrides)
    return Trade(**values)


def test_metrics_use_priced_positions_and_keep_missing_percentage_null():
    rows = [trade(1, 100), trade(2, 20), trade(3, -50), trade(4, 0), trade(5, None)]
    result = summarize(rows)
    assert result == dict(count=5, pnl_count=4, percentage_count=0, entry_days=1,
                         total_pnl=70, expectancy=17.5, median_pnl=10, win_rate=0.5,
                         profit_factor=2.4, no_losses=False, avg_winner=60, avg_loser=-50, avg_pnl_pct=None)
    rows[3].pnl_pct = Decimal(0)
    assert summarize(rows)["avg_pnl_pct"] == 0  # observed zero survives
    assert summarize(rows)["percentage_count"] == 1


def test_profit_concentration_removes_only_winners_and_includes_expiration():
    rows = [trade(1, 100), trade(2, 20), trade(3, -50, status="expired"), trade(4, 0), trade(5, None)]
    result = analyze(rows, {})
    assert result["concentration"][0]["remaining_pnl"] == -30
    assert result["concentration"][0]["gross_profit_share"] == pytest.approx(100 / 120)
    assert result["concentration"][1]["remaining_pnl"] == -50
    assert result["concentration"][1]["removed_count"] == 2
    assert result["summary"]["max_drawdown"] == -50
    assert result["curve"] == [{"date": "2026-09-01", "pnl": 70, "cumulative_pnl": 70}]
    assert result["coverage"]["missing_pnl"] == 1


def test_fractional_cents_are_rounded_after_decimal_aggregation():
    rows = [trade(1, "1.015"), trade(2, "-0.005")]
    result = analyze(rows, {})
    assert result["summary"]["total_pnl"] == 1.01
    assert result["summary"]["expectancy"] == 0.51
    assert result["summary"]["median_pnl"] == 0.51
    assert result["concentration"][0]["remaining_pnl"] == -0.01
    assert result["trades"][1]["realized_pnl"] == 1.02


@pytest.mark.parametrize("values,no_losses,factor", [([10, 0], True, None), ([-10, 0], False, 0), ([0], False, None)])
def test_profit_factor_without_both_sides(values, no_losses, factor):
    result = summarize([trade(i, value) for i, value in enumerate(values)])
    assert result["no_losses"] is no_losses
    assert result["profit_factor"] == factor


def test_empty_and_unpriced_samples_do_not_fabricate_zero_performance():
    for rows in ([], [trade(1, None)]):
        result = analyze(rows, {})
        for field in ("total_pnl", "win_rate", "expectancy", "median_pnl", "max_drawdown", "avg_pnl_pct"):
            assert result["summary"][field] is None
        assert result["curve"] == []
        assert result["concentration"][0]["gross_profit_share"] is None
        assert result["concentration"][0]["remaining_pnl"] is None
    losing = analyze([trade(1, -10)], {})
    assert losing["concentration"][0]["removed_count"] == 0
    assert losing["concentration"][0]["remaining_pnl"] == -10


def test_simultaneous_closes_do_not_invent_drawdown():
    timestamp = datetime(2026, 9, 1, 10)
    for rows in ([trade(1, 100, closed_at=timestamp), trade(2, -100, closed_at=timestamp)],
                 [trade(2, -100, closed_at=timestamp), trade(1, 100, closed_at=timestamp)]):
        assert analyze(rows, {})["summary"]["max_drawdown"] == 0


def test_date_filter_is_inclusive_new_york_close_date_and_accounts_are_exact():
    # UTC Sep 2 02:00 is still Sep 1 in New York.
    rows = [trade(1, 25, closed_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc)),
            trade(2, 50, closed_at=datetime(2026, 9, 2, 0)),
            trade(3, 500, account_id=OTHER_ACCOUNT), trade(4, 300, instrument_type="stock"),
            trade(5, 100, status="open"), trade(6, 10, closed_at=None)]
    result = analyze(rows, {}, account_id=str(ACCOUNT), instrument_type="option",
                     start=date(2026, 9, 1), end=date(2026, 9, 1))
    assert result["summary"]["total_pnl"] == 25
    assert result["summary"]["count"] == 1
    assert result["trades"][0]["closed_at"] == "2026-09-01T22:00:00"
    assert result["coverage"]["undated_closed_in_scope"] == 1


def test_repeat_state_uses_full_history_and_same_account_day_ticker():
    rows = [trade(1, None, instrument_type="stock", status="open", closed_at=None,
                  opened_at=datetime(2026, 9, 1, 9)),
            trade(2, 20, opened_at=datetime(2026, 9, 1, 10), closed_at=datetime(2026, 9, 2, 10)),
            trade(3, -5, account_id=OTHER_ACCOUNT, opened_at=datetime(2026, 9, 1, 11),
                  closed_at=datetime(2026, 9, 2, 11)),
            trade(4, 5, opened_at=datetime(2026, 9, 2, 9), closed_at=datetime(2026, 9, 2, 12)),
            trade(5, 10, ticker="QQQ", opened_at=datetime(2026, 9, 1, 11), closed_at=datetime(2026, 9, 2, 11))]
    result = analyze(rows, {}, instrument_type="option", start=date(2026, 9, 2))
    groups = {g["label"]: g for g in result["breakdowns"]["repeat_entry"]}
    assert groups["Repeat entry"]["trade_ids"] == [str(rows[1].id)]
    assert groups["First entry time"]["count"] == 3


def test_tag_overlap_and_unavailable_duration_preserve_denominators():
    rows = [trade(1, 10, hold_duration_mins=0), trade(2, -5, hold_duration_mins=None)]
    result = analyze(rows, {str(rows[0].id): ["Breakout", "Morning", "Morning"]})
    groups = {g["label"]: g for g in result["breakdowns"]["tag"]}
    assert groups["Breakout"]["count"] == groups["Morning"]["count"] == groups["Untagged"]["count"] == 1
    assert result["summary"]["count"] == 2
    holds = {g["label"]: g for g in result["breakdowns"]["hold_duration"]}
    assert holds["Under 15 min"]["count"] == holds["Unavailable"]["count"] == 1


def test_time_buckets_have_exclusive_upper_bounds_and_aware_time_conversion():
    rows = [trade(1, 1, opened_at=datetime(2026, 9, 1, 9, 44)),
            trade(2, 2, opened_at=datetime(2026, 9, 1, 9, 45)),
            trade(3, 3, opened_at=datetime(2026, 9, 1, 20, tzinfo=timezone.utc))]
    groups = {g["label"]: g["count"] for g in analyze(rows, {})["breakdowns"]["entry_time"]}
    assert groups == {"09:30–09:45": 1, "09:45–10:15": 1, "16:00 onward": 1}


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ACCOUNT, name="Individual", type="individual", last4="1113"))
        session.add(Account(id=OTHER_ACCOUNT, name="Other individual", type="individual", last4="2222"))
        session.add_all([trade(1, 100), trade(2, None), trade(3, 500, account_id=OTHER_ACCOUNT)])
        tag = Tag(id=UUID(int=20), name="Breakout", source="manual")
        session.add(tag)
        session.add(TradeTag(trade_id=UUID(int=101), tag_id=tag.id))
        session.commit()

    def override():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/stats")
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_endpoint_filters_individual_accounts_and_batches_tags(client):
    response = client.get("/stats/analytics", params={"account_id": str(ACCOUNT), "start": "2026-09-01", "end": "2026-09-01"})
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["total_pnl"] == 100
    assert result["summary"]["count"] == 2
    assert result["summary"]["win_rate"] == 1
    assert result["breakdowns"]["tag"][0]["label"] == "Breakout"
    assert result["breakdowns"]["tag"][1]["label"] == "Untagged"
    assert result["coverage"]["missing_pnl"] == 1


@pytest.mark.parametrize("params,status", [
    ({"start": "2026-09-02", "end": "2026-09-01"}, 400),
    ({"start": "2026-02-30"}, 422), ({"instrument_type": "crypto"}, 422),
    ({"account_id": "invalid"}, 422), ({"account_id": str(UUID(int=999))}, 404),
])
def test_endpoint_rejects_invalid_filters(client, params, status):
    assert client.get("/stats/analytics", params=params).status_code == status


def test_legacy_stats_missing_percentage_and_win_rate_are_consistent(client):
    result = client.get("/stats").json()
    assert result["win_rate"] == result["by_ticker"]["SPY"]["win_rate"] == 1
    assert result["by_ticker"]["SPY"]["avg_pnl_pct"] is None
