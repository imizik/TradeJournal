"""Stored option snapshot comparisons (Charts C4.6)."""

from datetime import date, datetime
import json

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine.options_history import attach_open_interest_changes
from app.models import OptionChainSnapshot, OptionSnapshotDay


def _row(session_date: date, expiration: date, contracts: list[list]) -> OptionChainSnapshot:
    return OptionChainSnapshot(session_date=session_date, underlying="SPY", expiration=expiration, provider="tradier",
                               captured_at=datetime(2026, 10, 6), contracts=len(contracts),
                               data_json=json.dumps({"columns": ["root", "type", "strike", "open_interest", "volume"],
                                                     "rows": contracts}))


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def test_change_uses_matching_contracts_and_leaves_a_new_strike_unavailable():
    engine = _session()
    expiration = date(2026, 10, 9)
    prior, current = date(2026, 10, 1), date(2026, 10, 2)
    rows = [{"strike": 100.0}, {"strike": 105.0}, {"strike": 110.0}]
    with Session(engine) as db:
        db.add_all([
            OptionSnapshotDay(session_date=prior, underlying="SPY", status="recorded"),
            OptionSnapshotDay(session_date=current, underlying="SPY", status="recorded"),
            _row(prior, expiration, [["SPY", "C", 100, 120, 10], ["SPY", "P", 100, 80, 4], ["SPY", "C", 105, 0, 0]]),
            _row(current, expiration, [["SPY", "C", 100, 150, 10], ["SPY", "P", 100, 70, 4],
                                       ["SPY", "C", 105, 0, 0], ["SPY", "C", 110, 25, 1]]),
        ])
        db.commit()
        attach_open_interest_changes(db, "SPY", "SPY", rows, [expiration.isoformat()])
    assert rows[0]["oi_change"] == {"session": "2026-10-02", "previous_session": "2026-10-01", "status": "ready", "calls": 30, "puts": -10}
    assert rows[1]["oi_change"]["calls"] == 0
    assert rows[2]["oi_change"]["calls"] is None
    assert rows[2]["oi_change"]["previous_session"] == "2026-10-01"


def test_unavailable_session_breaks_the_comparison_chain():
    engine = _session()
    expiration = date(2026, 10, 9)
    older, missed, current = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)
    rows = [{"strike": 100.0}]
    with Session(engine) as db:
        db.add_all([
            OptionSnapshotDay(session_date=older, underlying="SPY", status="recorded"),
            OptionSnapshotDay(session_date=missed, underlying="SPY", status="unavailable"),
            OptionSnapshotDay(session_date=current, underlying="SPY", status="recorded"),
            _row(older, expiration, [["SPY", "C", 100, 120, 10], ["SPY", "P", 100, 80, 4]]),
            _row(current, expiration, [["SPY", "C", 100, 150, 10], ["SPY", "P", 100, 70, 4]]),
        ])
        db.commit()
        attach_open_interest_changes(db, "SPY", "SPY", rows, [expiration.isoformat()])
    assert rows[0]["oi_change"] == {"session": "2026-10-05", "previous_session": "2026-10-02", "status": "unavailable"}
