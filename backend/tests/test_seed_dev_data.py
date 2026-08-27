"""
Guards the dev/browser-test fixture's contract.

scripts/seed_dev_data.py declares EXPECTED: the trades its fills should
reconstruct into. Browser tests assert against those values, so if the
reconstructor's behavior changes, the failure should surface here -- in a
fast unit run -- rather than as a confusing browser-test failure.

This also covers reconstruction shapes end to end through the production
rebuild path: a scale-in, a partial exit that keeps a position open while
banking realized P&L, an expiry write-off, fractional shares, a same-timestamp
tie-break, and account isolation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlmodel import Session, select

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_seed_module():
    path = BACKEND_DIR / "scripts" / "seed_dev_data.py"
    spec = importlib.util.spec_from_file_location("seed_dev_data", path)
    module = importlib.util.module_from_spec(spec)
    # scripts/ is not a package; register before exec so dataclass/annotation
    # resolution inside the module can find it.
    sys.modules["seed_dev_data"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    seed_module = _load_seed_module()
    database_path = tmp_path_factory.mktemp("seed") / "seed.db"
    seed_module.seed(f"sqlite:///{database_path}")
    return seed_module, f"sqlite:///{database_path}"


def _trades(database_url: str) -> list[dict]:
    from sqlmodel import create_engine

    from app.models import Account, Trade

    engine = create_engine(database_url)
    with Session(engine) as session:
        accounts = {a.id: a.last4 for a in session.exec(select(Account)).all()}
        return [
            {
                "ticker": trade.ticker,
                "account": accounts.get(trade.account_id),
                "status": trade.status,
                "realized_pnl": (
                    f"{trade.realized_pnl:.2f}"
                    if trade.realized_pnl is not None
                    else None
                ),
            }
            for trade in session.exec(select(Trade)).all()
        ]


def test_seed_reconstructs_exactly_the_expected_trades(seeded):
    seed_module, database_url = seeded
    expected = seed_module.EXPECTED

    actual = _trades(database_url)
    key = lambda row: (row["ticker"], row["account"])  # noqa: E731

    assert sorted(actual, key=key) == sorted(expected["trades"], key=key), (
        "The seed fixture no longer reconstructs its documented trades.\n"
        "Either the reconstructor changed behavior, or the fixture was edited "
        "without updating EXPECTED in scripts/seed_dev_data.py. Browser tests "
        "assert on these values."
    )
    assert len(actual) == expected["total_trades"]


def test_seed_is_stable_regardless_of_when_it_runs(seeded):
    """
    Option status depends on whether the expiration has passed, so a fixture
    with hard-coded dates changes meaning as the calendar moves: a position
    seeded as open becomes expired, and its P&L with it. The dates must be
    anchored to the run date.
    """
    seed_module, _ = seeded

    expirations = [
        values["expiration"]
        for values in seed_module._fills()
        if values["expiration"] is not None
    ]
    assert expirations, "expected option fills in the fixture"

    open_tickers = {
        trade["ticker"]
        for trade in seed_module.EXPECTED["trades"]
        if trade["status"] == "open"
    }
    open_expirations = [
        values["expiration"]
        for values in seed_module._fills()
        if values["expiration"] is not None and values["ticker"] in open_tickers
    ]
    assert open_expirations, "expected the fixture to hold an open option position"
    assert all(expiry > seed_module.TODAY for expiry in open_expirations), (
        "positions the fixture calls 'open' must expire in the future, or they "
        "will silently become 'expired' as the calendar moves"
    )


def test_seed_refuses_to_run_against_a_database_holding_real_fills(seeded, tmp_path):
    """The guard that makes this safe to point at a scratch database."""
    import uuid
    from datetime import datetime, timezone
    from decimal import Decimal

    from sqlmodel import SQLModel, create_engine

    from app.models import Account, Fill

    seed_module, _ = seeded
    database_path = tmp_path / "real.db"
    engine = create_engine(f"sqlite:///{database_path}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        account = Account(name="Roth IRA", type="roth_ira", last4="8267")
        session.add(account)
        session.commit()
        session.refresh(account)
        session.add(Fill(
            account_id=account.id,
            ticker="REAL",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("1"),
            executed_at=datetime.now(timezone.utc),
            raw_email_id="gmail-message-id-not-seeded",
        ))
        session.commit()

    with pytest.raises(SystemExit, match="Refusing to seed"):
        seed_module.seed(f"sqlite:///{database_path}")
