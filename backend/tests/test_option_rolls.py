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


def _setup(db, account):
    _fill(db, account, "buy_to_open", OLD, "2", "100", datetime(2026, 10, 27, 10, 0))


Z = (Decimal("70"), date(2026, 11, 6))
C = (Decimal("75"), date(2026, 11, 13))


def test_a_same_minute_sale_of_a_held_contract_is_not_the_new_leg():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _fill(db, account, "buy_to_open", Z, "2", "80", datetime(2026, 10, 28, 10, 0))
    _fill(db, account, "sell_to_close", Z, "2", "90", ROLL_AT)
    _roll(db, net="50")
    _fill(db, account, "sell_to_close", NEW, "2", "300", datetime(2026, 10, 29, 12, 0))
    assert resolve_rolls(db) == 1
    assert sum(t.realized_pnl for t in _trades(db).trades) == Decimal("320")


def test_a_chain_of_rolls_stays_unresolved_in_any_order():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _roll(db, net="50")
    db.add(OptionRollOrder(raw_email_id="roll-2", ticker="CRWV", contracts=Decimal(2), net_per_contract=Decimal(30), executed_at=datetime(2026, 10, 29, 11, 40)))
    _fill(db, account, "sell_to_close", C, "2", "300", datetime(2026, 10, 29, 12, 0))
    assert resolve_rolls(db) == 0 and len(unresolved_rolls(db)) == 2


def test_a_later_sale_of_the_old_contract_proves_it_was_not_rolled():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _roll(db)
    _fill(db, account, "sell_to_close", OLD, "2", "300", datetime(2026, 10, 29, 12, 0))
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 10, 29, 12, 1))
    assert resolve_rolls(db) == 0


def test_a_partial_sale_or_two_candidates_stay_unresolved_until_clear():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _roll(db, net="50")
    _fill(db, account, "sell_to_close", NEW, "1", "200", datetime(2026, 10, 29, 12, 0))
    assert resolve_rolls(db) == 0
    _fill(db, account, "sell_to_close", Z, "2", "70", datetime(2026, 10, 29, 12, 5))
    assert resolve_rolls(db) == 0
    _fill(db, account, "sell_to_close", NEW, "1", "220", datetime(2026, 10, 29, 12, 6))
    assert resolve_rolls(db) == 0  # the new leg now adds up, but so does the unrelated sale


def test_a_rebuy_before_the_sale_is_not_a_new_leg():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _roll(db, net="50")
    _fill(db, account, "sell_to_close", NEW, "1", "200", datetime(2026, 10, 29, 12, 0))
    _fill(db, account, "buy_to_open", NEW, "1", "120", datetime(2026, 10, 29, 12, 5))
    _fill(db, account, "sell_to_close", NEW, "1", "150", datetime(2026, 10, 29, 12, 9))
    assert resolve_rolls(db) == 0


def test_an_earlier_unresolved_order_blocks_later_ones_on_the_ticker_only():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _roll(db, net="50")
    db.add(OptionRollOrder(raw_email_id="roll-2", ticker="CRWV", contracts=Decimal(2), net_per_contract=Decimal(30), executed_at=datetime(2026, 10, 30, 11, 0), credit_mentioned=False))
    db.flush()
    assert resolve_rolls(db) == 0 and len(unresolved_rolls(db)) == 2


def test_a_sale_long_after_the_order_is_no_evidence():
    db = _db()
    account = _account(db)
    _fill(db, account, "buy_to_open", (OLD[0], date(2027, 1, 15)), "2", "100", datetime(2026, 10, 27, 10, 0))
    _roll(db)
    _fill(db, account, "sell_to_close", NEW, "2", "270", datetime(2026, 12, 15, 10, 0))
    assert resolve_rolls(db) == 0


def test_separate_rolls_resolve_the_same_together_as_one_at_a_time():
    db = _db()
    account = _account(db)
    _setup(db, account)
    _roll(db, net="50")
    _fill(db, account, "sell_to_close", NEW, "2", "300", datetime(2026, 10, 29, 12, 0))
    _fill(db, account, "buy_to_open", Z, "2", "80", datetime(2026, 10, 29, 13, 0))
    db.add(OptionRollOrder(raw_email_id="roll-2", ticker="CRWV", contracts=Decimal(2), net_per_contract=Decimal(30), executed_at=datetime(2026, 10, 30, 11, 0)))
    _fill(db, account, "sell_to_close", C, "2", "200", datetime(2026, 10, 30, 12, 0))
    assert resolve_rolls(db) == 2 and unresolved_rolls(db) == []
    assert sum(t.realized_pnl for t in _trades(db).trades) == Decimal("480")  # (600 - 200 - 100) + (400 - 160 - 60)
