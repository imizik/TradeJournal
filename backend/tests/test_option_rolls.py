"""A two-leg email's fills, derived from the book, and every case that must stay unresolved."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import Session, SQLModel, create_engine, select

from app.engine.option_rolls import resolve_rolls, unresolved_rolls
from app.engine.reconstructor import FillInput, reconstruct
from app.models import Account, Fill, OptionRollOrder

ROLL_AT = datetime(2026, 10, 29, 11, 16)
OLD = (Decimal("63.5"), date(2026, 10, 30))
NEW = (Decimal("65"), date(2026, 11, 6))


def _db():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _account(db, last4="8267"):
    account = Account(name=last4, type="roth_ira", last4=last4)
    db.add(account)
    db.flush()
    return account


def _fill(db, account, side, contract, n, price, at, kind="call", ticker="CRWV"):
    db.add(Fill(account_id=account.id, ticker=ticker, instrument_type="option", side=side, contracts=Decimal(n), price=Decimal(price),
                executed_at=at, raw_email_id=f"m{uuid.uuid4()}", option_type=kind, strike=contract[0], expiration=contract[1]))
    db.flush()


def _roll(db, n="2", net="132", **extra):
    db.add(OptionRollOrder(raw_email_id="roll-1", ticker="CRWV", contracts=Decimal(n), net_per_contract=Decimal(net), executed_at=ROLL_AT, **extra))
    db.flush()


def _book(db, account):
    _fill(db, account, "buy_to_open", OLD, "2", "100", datetime(2026, 10, 27, 10, 0))
    _fill(db, account, "buy_to_open", OLD, "4", "150", datetime(2026, 10, 27, 11, 0))
    _fill(db, account, "sell_to_close", OLD, "4", "242", datetime(2026, 10, 28, 14, 38))


def _trades(db):
    rows = db.exec(select(Fill)).all()
    result = reconstruct([FillInput(id=f.id, account_id=f.account_id, ticker=f.ticker, instrument_type=f.instrument_type, side=f.side,
                                    contracts=Decimal(str(f.contracts)), price=Decimal(str(f.price)), executed_at=f.executed_at,
                                    option_type=f.option_type, strike=Decimal(str(f.strike)), expiration=f.expiration) for f in rows],
                         today=date(2026, 11, 20))
    return result


def test_the_crwv_roll_gives_the_exact_total_and_closes_the_old_contract():
    db = _db()
    account = _account(db)
    _book(db, account)
    _roll(db)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 17))
    assert resolve_rolls(db) == 1 and unresolved_rolls(db) == []
    result = _trades(db)
    assert result.anomalies == []
    assert all(t.status == "closed" for t in result.trades)
    new = next(t for t in result.trades if t.strike == NEW[0] and t.expiration == NEW[1])
    assert new.avg_entry_premium == Decimal("282") and new.realized_pnl == Decimal("-24")  # cost 150 + 132, sold 270
    old = next(t for t in result.trades if t.strike == OLD[0])
    # 2@100 and 2@150 sold at 242 realize +284 + 184 = 468 first; the rolled 2@150 close flat.
    assert old.realized_pnl == Decimal("468")
    assert sum(t.realized_pnl for t in result.trades) == Decimal("444")  # 4*242 + 2*270 - 2*100 - 4*150 - 264


def test_running_twice_adds_nothing():
    db = _db()
    account = _account(db)
    _book(db, account)
    _roll(db)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 17))
    assert resolve_rolls(db) == 1 and resolve_rolls(db) == 0
    assert len(db.exec(select(Fill).where(Fill.raw_email_id.like("roll:%"))).all()) == 2


def test_before_the_new_contract_is_sold_it_stays_unresolved():
    db = _db()
    _book(db, _account(db))
    _roll(db)
    assert resolve_rolls(db) == 0 and [r.raw_email_id for r in unresolved_rolls(db)] == ["roll-1"]


def test_two_possible_old_contracts_stay_unresolved():
    db = _db()
    account = _account(db)
    _book(db, account)
    _fill(db, account, "buy_to_open", (Decimal("70"), date(2026, 10, 30)), "2", "50", datetime(2026, 10, 28, 9, 40))
    _roll(db)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 17))
    assert resolve_rolls(db) == 0


def test_a_put_cannot_pair_with_a_call_and_another_account_does_not_pair():
    db = _db()
    account = _account(db)
    _book(db, account)
    _roll(db)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 17), kind="put")
    _fill(db, _account(db, "1111"), "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 18))
    assert resolve_rolls(db) == 0


def test_an_email_mentioning_a_credit_is_never_read_as_a_debit():
    db = _db()
    account = _account(db)
    _book(db, account)
    _roll(db, credit_mentioned=True)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 17))
    assert resolve_rolls(db) == 0 and len(unresolved_rolls(db)) == 1


def test_a_fill_missing_its_contract_details_does_not_break_a_rebuild():
    db = _db()
    account = _account(db)
    _book(db, account)
    db.add(Fill(account_id=account.id, ticker="CRWV", instrument_type="option", side="buy_to_open", contracts=Decimal(1), price=Decimal(1),
                executed_at=datetime(2026, 10, 28, 9, 40), raw_email_id="m-bare"))
    _roll(db)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 17))
    assert resolve_rolls(db) == 1
