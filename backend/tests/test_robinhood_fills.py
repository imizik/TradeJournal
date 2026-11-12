"""Fills from Robinhood's order history (app/engine/robinhood_fills.py, docs/robinhood-order-fills.md).

Everything runs against tests/robinhood_fake.py (the order-history shapes observed on 2026-11-12, values invented) and
a scratch SQLite file per test: nothing here reaches Robinhood, Gmail or any hosted database. The email side runs
through the real import (``_import_fills_from_gmail``) with the Gmail poll replaced by parsed emails."""

from __future__ import annotations

import itertools
import json
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import gmail_poller
from app.engine import robinhood_book as rb
from app.engine import robinhood_fills as rf
from app.engine import robinhood_read as rh
from app.engine.chart_math import ET
from app.engine.email_parser import ParsedFill
from app.models import Account, Fill, RobinhoodExecution, RobinhoodReconciliation, Trade, TradeFill
from app.routers import fills as fills_router
from tests.robinhood_fake import FakeRobinhood, equity_order, execution, option_order, token_file

ROTH, INDIVIDUAL = "333338267", "111118888"  # the fake's account numbers; the journal knows them by 8267 and 8888
DAY = "2026-11-12"  # a Thursday; New York is on EST (UTC-5)


def utc(hh: int, mm: int, ss: float = 0, day: str = DAY) -> str:
    """A New York wall-clock time on ``day`` as Robinhood's UTC timestamp."""
    moment = datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET) + timedelta(seconds=ss)
    return moment.astimezone(rf.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def epoch(hh: int, mm: int, day: str = DAY) -> float:
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET).timestamp()


def email(raw_id, ticker, side, qty, price, hh, mm, *, kind=None, strike=None, expiry=None, last4="8267", day=DAY):
    """A parsed fill email: minute resolution, the option price per contract as the parser stores it."""
    at = datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET)
    option = kind is not None
    return ParsedFill(ticker=ticker, side=side, contracts=Decimal(str(qty)), price=Decimal(str(price)), executed_at=at,
                      instrument_type="option" if option else "stock", raw_email_id=raw_id, account_last4=last4,
                      account_type="roth_ira" if last4 == "8267" else "individual", option_type=kind,
                      strike=Decimal(strike) if strike else None,
                      expiration=datetime.fromisoformat(expiry).date() if expiry else None)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'journal.sqlite'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Account(id=uuid.UUID(int=1), name="Roth IRA", type="roth_ira", last4="8267"))
        s.add(Account(id=uuid.UUID(int=2), name="Individual", type="individual", last4="8888"))
        s.commit()
    yield engine
    engine.dispose()


class Desk:
    """One journal, the fake Robinhood and the switches: ``poll()`` is one poller pass, ``emails()`` one Gmail import
    plus its rebuild, as the push pipeline runs them."""

    def __init__(self, engine, tmp_path, monkeypatch, mode="on"):
        self.engine, self.mode, self.monkeypatch = engine, mode, monkeypatch
        self.fake = FakeRobinhood()
        self.fake.options = {}
        monkeypatch.setattr(rh, "_transport", self.fake.transport)
        token = token_file(tmp_path / "robinhood-token.json")
        self.feed = rb.Feed(settings_fn=lambda: rb.Settings(enabled=True, token_file=str(token), accounts=("roth ira", "mcp")))
        self.clock = epoch(16, 30)
        self.poller = self.new_poller()

    def new_poller(self):
        return rf.Poller(self.engine, self.feed, now=lambda: self.clock, mode_fn=lambda: self.mode)

    def at(self, hh, mm, day=DAY):
        self.clock = epoch(hh, mm, day)
        return self

    def poll(self):
        status = self.poller.run_once()
        assert status["state"] in ("ok", "off", "feed off or signed out"), status
        return status

    def emails(self, *parsed):
        self.monkeypatch.setattr(gmail_poller, "poll_new_fills", lambda **_kw: list(parsed))
        with Session(self.engine) as s:
            result = fills_router._import_fills_from_gmail(s, start_enrichment=False)
            if result["saved"]:
                fills_router._rebuild_trades(s, anomalies_label="test push")
                s.commit()
        return result

    def option(self, order):
        self.fake.option_orders.setdefault(ROTH, []).append(order)

    def stock(self, order, account=ROTH):
        self.fake.equity_orders.setdefault(account, []).append(order)

    # reads
    def fills(self):
        with Session(self.engine) as s:
            return sorted(((f.raw_email_id, f.ticker, f.side, Decimal(str(f.contracts)), Decimal(str(f.price)), f.executed_at)
                           for f in s.exec(select(Fill)).all()), key=lambda r: (r[5], r[0]))

    def outcomes(self):
        with Session(self.engine) as s:
            return {r.key: r for r in s.exec(select(RobinhoodReconciliation)).all()}

    def by_order(self, order_id):
        return self.outcomes()[f"order:{order_id}"]

    def trades(self):
        with Session(self.engine) as s:
            return sorted((t.ticker, t.status, Decimal(str(t.contracts)), t.realized_pnl and Decimal(str(t.realized_pnl)))
                          for t in s.exec(select(Trade)).all())


@pytest.fixture
def desk(engine, tmp_path, monkeypatch):
    return Desk(engine, tmp_path, monkeypatch)


MU = dict(kind="call", strike="835.0000", expiry="2026-11-13")


def mu_buy(order_id, qty, price, hh, mm, ss=12.0, **kw):
    return option_order(order_id, "MU", [execution("x-" + order_id, price, qty, utc(hh, mm, ss))], **kw)


# --------------------------------------------------------------------------- parsing

def test_parsing_follows_the_journal_conventions_and_skips_what_it_cannot_record():
    data = {"orders": [
        mu_buy("o1", "2.00000", "1.93000000", 12, 15, ss=19.102),
        option_order("o2", "MU", [execution("x2", "2.40000000", "2.00000", "2026-11-12T17:45:00.93593196Z")], side="sell", effect="close"),
        option_order("bad", "MU", [execution("", "1.0", "1", utc(12, 0)), execution("x3", "abc", "1", utc(12, 0)),
                                   execution("x4", "1.0", "1", "2026-11-12T12:00:00")]),  # no id, odd price, no zone
        option_order("roll", "CRWV", [], legs=[
            {"side": "sell", "position_effect": "close", "option_type": "call", "strike_price": "70", "expiration_date": "2026-11-21",
             "executions": [execution("r1", "1.0", "1", utc(13, 0))]},
            {"side": "buy", "position_effect": "open", "option_type": "call", "strike_price": "75", "expiration_date": "2026-11-28",
             "executions": [execution("r2", "1.5", "1", utc(13, 0))]}]),
    ]}
    got = rf.option_executions(data, "8267")
    assert [(e.execution_id, e.side, e.price, e.contracts, e.legs) for e in got] == [
        ("x-o1", "buy_to_open", Decimal("193.00000000000000"), Decimal("2.00000"), 1),
        ("x2", "sell_to_close", Decimal("240.0000000000000000"), Decimal("2.00000"), 1),
        ("r1", "sell_to_close", Decimal("100.00000"), Decimal("1"), 2), ("r2", "buy_to_open", Decimal("150.00000"), Decimal("1"), 2)]
    first = got[0]
    assert (first.executed_at, first.strike, first.option_type, str(first.expiration)) == (
        datetime(2026, 11, 12, 12, 15, 19, 102000), Decimal("835.0000"), "call", "2026-11-13")  # New York wall clock
    assert got[1].executed_at == datetime(2026, 11, 12, 12, 45, 0, 935931)

    fractional = equity_order("e1", "RKLB", [execution("f1", "67.220000", "3.000000", "2026-11-11T17:49:37.502Z"),
                                             execution("f2", "67.220000", "0.069042", "2026-11-11T17:49:37.502Z")], side="sell")
    stocks = rf.equity_executions({"orders": [fractional, {"id": "x", "symbol": "rklb!", "side": "sell", "state": "filled"}]}, "8267")
    assert [(e.side, e.contracts, e.price, e.instrument_type) for e in stocks] == [
        ("sell", Decimal("3.000000"), Decimal("67.220000"), "stock"), ("sell", Decimal("0.069042"), Decimal("67.220000"), "stock")]


# --------------------------------------------------------------------------- the cases of the design

def test_an_order_and_its_email_pair_whichever_comes_first_and_make_one_fill(desk):
    desk.option(mu_buy("o1", "2.00000", "1.93000000", 10, 5))
    desk.at(10, 6).poll()  # Robinhood first: provisional, not a fill
    assert desk.fills() == [] and desk.by_order("o1").outcome == "pending"
    desk.at(10, 9).emails(email("m1", "MU", "buy_to_open", 2, 193, 10, 5, **MU))
    desk.at(10, 10).poll()
    row = desk.by_order("o1")
    assert (row.outcome, row.journal_source, row.action) == ("matched", "email", "none")
    assert [f[0] for f in desk.fills()] == ["m1"]

    # The other way round: the email first, then the order.
    desk.option(mu_buy("o2", "1.00000", "2.10000000", 11, 0))
    desk.at(11, 1).emails(email("m2", "MU", "buy_to_open", 1, 210, 11, 0, **MU))
    desk.at(11, 2).poll()
    assert desk.by_order("o2").outcome == "matched" and [f[0] for f in desk.fills()] == ["m1", "m2"]


def test_an_order_whose_email_never_comes_is_listed_not_written(desk):
    desk.option(mu_buy("o1", "1.00000", "1.50000000", 10, 0))
    desk.at(10, 20).poll()
    assert desk.by_order("o1").outcome == "pending"
    desk.at(10, 31).poll()  # past the 30-minute grace
    row = desk.by_order("o1")
    assert (row.outcome, row.action, row.fill_id) == ("order_only", "none", None)
    assert desk.fills() == []
    desk.at(11, 0).emails(email("late", "MU", "buy_to_open", 1, 150, 10, 0, **MU))  # a very late email still pairs
    desk.at(11, 1).poll()
    assert desk.by_order("o1").outcome == "matched"


def test_several_executions_of_one_order_pair_with_the_one_email_at_its_rounded_average(desk):
    desk.option(option_order("o1", "NVDA", [execution("a", "3.10000000", "1.00000", utc(11, 0, 5)),
                                            execution("b", "3.12000000", "2.00000", utc(11, 0, 40))],
                             strike="200.0000", expiry="2026-11-21"))
    desk.at(11, 2).emails(email("m1", "NVDA", "buy_to_open", 3, 311, 11, 0, kind="call", strike="200", expiry="2026-11-21"))
    desk.at(11, 3).poll()
    row = desk.by_order("o1")
    assert row.outcome == "matched" and Decimal(str(row.rh_price)) == Decimal("311.333333") and Decimal(str(row.journal_price)) == 311
    with Session(desk.engine) as s:
        assert len(s.exec(select(RobinhoodExecution)).all()) == 2  # both execution ids recorded


def test_a_partial_fill_waits_until_the_order_is_done(desk):
    order = option_order("o1", "NVDA", [execution("a", "3.50000000", "1.00000", utc(13, 10))], side="sell", effect="close",
                         strike="200.0000", expiry="2026-11-21", quantity="3.00000", state="partially_filled")
    desk.option(order)
    desk.at(14, 0).poll()  # an hour on, still working: never order-only, never a mismatch
    row = desk.by_order("o1")
    assert (row.outcome, Decimal(str(row.rh_contracts))) == ("pending", 1)
    order["legs"][0]["executions"].append(execution("b", "3.60000000", "2.00000", utc(14, 5)))
    order["state"] = "filled"
    desk.at(14, 6).emails(email("m1", "NVDA", "sell_to_close", 3, 357, 14, 5, kind="call", strike="200", expiry="2026-11-21"))
    desk.at(14, 7).poll()
    row = desk.by_order("o1")
    assert row.outcome == "matched" and Decimal(str(row.rh_contracts)) == 3 and Decimal(str(row.rh_price)) == Decimal("356.666667")


def test_two_identical_trades_seconds_apart_pair_one_to_one(desk):
    desk.option(mu_buy("o1", "1.00000", "1.50000000", 14, 0, ss=1))
    desk.option(mu_buy("o2", "1.00000", "1.50000000", 14, 0, ss=20))
    desk.at(14, 2).emails(email("m1", "MU", "buy_to_open", 1, 150, 14, 0, **MU), email("m2", "MU", "buy_to_open", 1, 150, 14, 0, **MU))
    desk.at(14, 3).poll()
    a, b = desk.by_order("o1"), desk.by_order("o2")
    assert a.outcome == b.outcome == "matched" and a.fill_id != b.fill_id
    assert len(desk.fills()) == 2  # two trades, two fills: neither doubled nor merged
    desk.at(14, 4).poll()
    assert (desk.by_order("o1").fill_id, desk.by_order("o2").fill_id) == (a.fill_id, b.fill_id)  # pairs are stable


def test_a_fractional_sale_that_fills_as_two_executions_is_one_order(desk):
    desk.stock(equity_order("e1", "RKLB", [execution("f1", "67.220000", "3.000000", utc(12, 49, 37.502)),
                                           execution("f2", "67.220000", "0.069042", utc(12, 49, 37.502))], side="sell"))
    desk.at(12, 51).emails(email("m1", "RKLB", "sell", "3.069042", "67.22", 12, 49))
    desk.at(12, 52).poll()
    row = desk.by_order("e1")
    assert row.outcome == "matched" and Decimal(str(row.rh_contracts)) == Decimal("3.069042")


@pytest.mark.parametrize("qty,price,outcome", [
    (2, 193.4, "matched"),  # 0.4 c a share: the email's rounding
    (2, 194, "mismatch"),  # a cent a share is a real difference
    (3, 193, "mismatch"),  # a different quantity
])
def test_a_small_difference_is_rounding_a_larger_one_is_a_mismatch_listed_with_both_versions(desk, qty, price, outcome):
    desk.option(mu_buy("o1", "2.00000", "1.93000000", 10, 5))
    desk.at(10, 7).emails(email("m1", "MU", "buy_to_open", qty, price, 10, 5, **MU))
    before = desk.fills()
    desk.at(10, 8).poll()
    if outcome == "mismatch":  # a near miss waits out the email grace: an exact email may still come
        assert desk.by_order("o1").outcome == "pending"
        desk.at(10, 40).poll()
    row = desk.by_order("o1")
    assert row.outcome == outcome
    assert (Decimal(str(row.rh_contracts)), Decimal(str(row.rh_price))) == (2, 193)
    assert (Decimal(str(row.journal_contracts)), Decimal(str(row.journal_price))) == (qty, Decimal(str(price)))
    assert desk.fills() == before  # never auto-fixed: the email's fill stays exactly as it was


# --------------------------------------------------------------------------- what only the order history sees

def recurring_vti(order_id="r1", hh=9, mm=35):
    return equity_order(order_id, "VTI", [execution("v-" + order_id, "317.500000", "0.299212", utc(hh, mm, 2))], agent="recurring",
                        dollars="95.000000", created_at=utc(9, 0))


def test_a_recurring_buy_is_written_once_and_survives_polls_restarts_and_rereads(desk):
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    row = desk.by_order("r1")
    assert (row.outcome, row.action, row.journal_source) == ("order_only", "wrote_fill", "robinhood")
    fills = desk.fills()
    assert fills == [("robinhood:r1", "VTI", "buy", Decimal("0.299212"), Decimal("317.500000"), datetime(2026, 11, 12, 9, 35, 2))]
    assert desk.trades() == [("VTI", "open", Decimal("0.299212"), None)]  # rebuilt in the same transaction

    desk.at(9, 37).poll()
    desk.poller = desk.new_poller()  # a restart
    desk.at(9, 38).poll()
    desk.fake.order_page = 1  # and a week of history re-read page by page
    desk.at(10, 0, day="2026-11-16").poll()
    assert desk.fills() == fills
    with Session(desk.engine) as s:
        assert len(s.exec(select(RobinhoodExecution)).all()) == 1


def test_shadow_records_what_it_would_write_and_writes_nothing(desk):
    desk.mode = "shadow"
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    row = desk.by_order("r1")
    assert (row.outcome, row.action, row.fill_id, row.mode) == ("order_only", "would_write_fill", None, "shadow")
    assert desk.fills() == [] and desk.trades() == []
    desk.mode = "on"  # switched on later: the same order is written then, once
    desk.at(9, 40).poll()
    assert [f[0] for f in desk.fills()] == ["robinhood:r1"]


def test_a_recurring_buy_already_backfilled_by_hand_is_paired_not_written(desk):
    with Session(desk.engine) as s:  # the July backfill's csvfix convention: a manual fill with a rough time
        s.add(Fill(account_id=uuid.UUID(int=1), ticker="VTI", instrument_type="stock", side="buy", contracts=Decimal("0.299212"),
                   price=Decimal("317.50"), executed_at=datetime(2026, 11, 12, 0, 0), raw_email_id="manual:csvfix-vti"))
        s.commit()
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    row = desk.by_order("r1")
    assert (row.outcome, row.journal_source, row.action) == ("matched", "manual", "none")
    assert [f[0] for f in desk.fills()] == ["manual:csvfix-vti"]


def test_an_email_for_a_written_order_never_becomes_a_second_fill(desk):
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    result = desk.at(9, 40).emails(email("surprise", "VTI", "buy", "0.299212", "317.50", 9, 35))
    assert result["saved"] == 0 and [f[0] for f in desk.fills()] == ["robinhood:r1"]
    row = desk.by_order("r1")
    assert (row.outcome, row.journal_email_id) == ("order_only", "surprise")
    assert "agrees" in row.note
    assert desk.at(9, 45).emails(email("surprise", "VTI", "buy", "0.299212", "317.50", 9, 35))["saved"] == 0  # known now


def test_a_same_quantity_email_at_another_price_is_a_mismatch_and_still_one_fill(desk):
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    desk.at(9, 40).emails(email("odd", "VTI", "buy", "0.299212", "320.00", 9, 35))
    row = desk.by_order("r1")
    assert (row.outcome, row.journal_email_id, Decimal(str(row.journal_price))) == ("mismatch", "odd", Decimal("320.00"))
    assert [f[0] for f in desk.fills()] == ["robinhood:r1"]
    desk.at(9, 41).poll()  # the next pass keeps it listed
    assert desk.by_order("r1").outcome == "mismatch"


def test_an_email_of_another_quantity_near_a_written_order_is_another_trade_and_imported(desk):
    """A hand buy of the same stock minutes after a recurring buy: its email is the record for it, never swallowed."""
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    result = desk.at(9, 40).emails(email("hand", "VTI", "buy", 10, "317.60", 9, 37))
    assert result["saved"] == 1 and [f[0] for f in desk.fills()] == ["robinhood:r1", "hand"]
    row = desk.by_order("r1")
    assert (row.outcome, row.journal_email_id) == ("order_only", None)
    desk.at(9, 41).poll()
    assert desk.by_order("r1").outcome == "order_only"  # not a duplicate either: a different quantity


def test_a_recurring_buy_never_takes_a_hand_buys_email_of_another_quantity(desk):
    """Risk review F3: the recurring order must not claim the hand buy's email as a near miss and stay unwritten."""
    desk.stock(recurring_vti())
    desk.stock(equity_order("hand", "VTI", [execution("h1", "317.600000", "10.000000", utc(9, 37, 10))]))
    desk.at(9, 39).emails(email("hand-mail", "VTI", "buy", 10, "317.60", 9, 37))
    desk.at(9, 40).poll()
    assert (desk.by_order("hand").outcome, desk.by_order("r1").action) == ("matched", "wrote_fill")
    assert [f[0] for f in desk.fills()] == ["robinhood:r1", "hand-mail"]


def test_a_scale_in_with_a_late_first_email_pairs_each_order_exactly(desk):
    """Risk review F3: buy 1, then 2, the first email a minute late: no order takes the other's email as a mismatch."""
    desk.option(mu_buy("a", "1.00000", "1.50000000", 10, 0, ss=10))
    desk.option(mu_buy("b", "2.00000", "1.60000000", 10, 2, ss=10))
    desk.at(10, 3).emails(email("m-b", "MU", "buy_to_open", 2, 160, 10, 2, **MU))
    desk.at(10, 3).poll()
    assert (desk.by_order("a").outcome, desk.by_order("b").outcome) == ("pending", "matched")
    desk.at(10, 4).emails(email("m-a", "MU", "buy_to_open", 1, 150, 10, 0, **MU))
    desk.at(10, 5).poll()
    desk.at(11, 0).poll()
    assert (desk.by_order("a").outcome, desk.by_order("b").outcome) == ("matched", "matched")
    assert desk.by_order("a").journal_price == Decimal(150)


def test_a_late_exact_email_replaces_an_earlier_mismatch(desk):
    desk.option(mu_buy("a", "1.00000", "1.50000000", 10, 0))
    desk.at(10, 1).emails(email("other", "MU", "buy_to_open", 3, 150, 10, 1, **MU))  # someone else's fill, nearby
    desk.at(10, 40).poll()
    assert desk.by_order("a").outcome == "mismatch"
    desk.at(10, 41).emails(email("m-a", "MU", "buy_to_open", 1, 150, 10, 0, **MU))
    desk.at(10, 42).poll()
    row = desk.by_order("a")
    assert row.outcome == "matched" and row.journal_contracts == 1


def test_a_hand_buy_without_its_email_cannot_take_a_backfilled_recurring_buy(desk):
    """Risk review F4: the backfill pairs with the recurring order exactly, so nothing is written twice."""
    with Session(desk.engine) as s:
        s.add(Fill(account_id=uuid.UUID(int=1), ticker="VTI", instrument_type="stock", side="buy", contracts=Decimal("0.299212"),
                   price=Decimal("317.50"), executed_at=datetime(2026, 11, 12, 0, 0), raw_email_id="manual:csvfix-vti"))
        s.commit()
    desk.stock(equity_order("hand", "VTI", [execution("h1", "317.600000", "10.000000", utc(9, 31))]))
    desk.stock(recurring_vti())
    desk.at(10, 30).poll()
    assert (desk.by_order("r1").outcome, desk.by_order("r1").journal_source) == ("matched", "manual")
    assert (desk.by_order("hand").outcome, desk.by_order("hand").fill_id) == ("order_only", None)
    assert [f[0] for f in desk.fills()] == ["manual:csvfix-vti"]


def test_a_backfill_long_after_a_written_buy_is_still_listed_as_a_possible_duplicate(desk):
    """Risk review F5: the duplicate check covers every written fill, not only the last week's."""
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    with Session(desk.engine) as s:
        s.add(Fill(account_id=uuid.UUID(int=1), ticker="VTI", instrument_type="stock", side="buy", contracts=Decimal("0.299212"),
                   price=Decimal("317.5"), executed_at=datetime(2026, 11, 12, 0, 0), raw_email_id="manual:csvfix-vti-late"))
        s.commit()
    desk.at(10, 0, day="2026-11-25").poll()
    row = desk.by_order("r1")
    assert row.outcome == "mismatch" and "possible duplicate" in row.note and row.journal_source == "manual"
    assert len(desk.fills()) == 2


def test_a_duplicate_flag_clears_when_its_fill_turns_out_to_be_another_order(desk):
    """Recheck S2: a hand buy of exactly the recurring quantity, its email in before its order is read."""
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    desk.at(11, 0).emails(email("hand", "VTI", "buy", "0.299212", "318.00", 10, 50))
    desk.at(11, 1).poll()
    assert "possible duplicate" in desk.by_order("r1").note
    desk.stock(equity_order("h", "VTI", [execution("h1", "318.000000", "0.299212", utc(10, 50, 3))]))
    desk.at(11, 2).poll()
    r1 = desk.by_order("r1")
    assert (desk.by_order("h").outcome, r1.outcome, r1.action, r1.journal_source) == ("matched", "order_only", "wrote_fill", "robinhood")
    assert [f[0] for f in desk.fills()] == ["robinhood:r1", "hand"]


def test_a_hand_entry_after_a_written_order_is_listed_as_a_possible_duplicate(desk):
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    with Session(desk.engine) as s:
        s.add(Fill(account_id=uuid.UUID(int=1), ticker="VTI", instrument_type="stock", side="buy", contracts=Decimal("0.299212"),
                   price=Decimal("317.5"), executed_at=datetime(2026, 11, 12, 12, 0), raw_email_id="manual:vti-by-hand"))
        s.commit()
    desk.at(12, 5).poll()
    row = desk.by_order("r1")
    assert row.outcome == "mismatch" and "possible duplicate" in row.note and row.journal_source == "manual"
    assert len(desk.fills()) == 2  # listed for the owner, nothing removed


def test_an_email_fill_no_order_explains_is_listed_only_where_the_window_was_read(desk):
    desk.at(15, 0).emails(email("lonely", "AMD", "buy_to_open", 1, 250, 11, 0, kind="put", strike="240", expiry="2026-11-21"))
    desk.at(15, 1).poll()
    rows = [r for r in desk.outcomes().values() if r.outcome == "email_only"]
    assert len(rows) == 1 and rows[0].journal_source == "email" and rows[0].ticker == "AMD"

    desk.fake.fail = {"get_option_orders"}  # option orders did not read: no option email fill is judged
    with Session(desk.engine) as s:
        for r in s.exec(select(RobinhoodReconciliation)).all():
            s.delete(r)
        s.commit()
    desk.at(15, 2).poll()
    assert not [r for r in desk.outcomes().values() if r.outcome == "email_only"]


# --------------------------------------------------------------------------- what keeps working as today

def test_expirations_assignments_and_rolls_stay_with_the_email_and_the_rebuild(desk):
    """A position that expires (or is assigned) has no closing order: the rebuild closes it as today. A two-leg order is
    left to the roll email; its legs are recorded but never paired or written."""
    desk.option(option_order("o1", "AMD", [execution("x1", "1.00000000", "1.00000", utc(10, 0, 3))], kind="put",
                             strike="240.0000", expiry="2026-11-06"))
    desk.option(option_order("roll", "CRWV", [], legs=[
        {"side": "sell", "position_effect": "close", "option_type": "call", "strike_price": "70", "expiration_date": "2026-11-21",
         "executions": [execution("r1", "1.0", "1", utc(13, 0))]},
        {"side": "buy", "position_effect": "open", "option_type": "call", "strike_price": "75", "expiration_date": "2026-11-28",
         "executions": [execution("r2", "1.5", "1", utc(13, 0))]}]))
    desk.at(10, 2).emails(email("m1", "AMD", "buy_to_open", 1, 100, 10, 0, kind="put", strike="240", expiry="2026-11-06"))
    with Session(desk.engine) as s:
        s.add(fills_router.OptionRollOrder(raw_email_id="roll-mail", ticker="CRWV", contracts=Decimal(1),
                                           net_per_contract=Decimal(50), credit_mentioned=False, executed_at=datetime(2026, 11, 12, 13, 0)))
        s.commit()
    trades_without = desk.trades()
    desk.at(16, 0).poll()
    assert desk.trades() == trades_without
    assert desk.by_order("o1").outcome == "matched"
    roll = desk.by_order("roll")
    assert (roll.outcome, roll.action, roll.fill_id) == ("order_only", "none", None) and "two-leg" in roll.note
    assert [f[0] for f in desk.fills()] == ["m1"]


def test_resync_keeps_written_fills_and_does_not_reimport_an_email_already_recorded(desk, monkeypatch):
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    desk.at(9, 40).emails(email("surprise", "VTI", "buy", "0.299212", "317.50", 9, 35))
    monkeypatch.setattr(gmail_poller, "poll_new_fills",
                        lambda **_kw: [email("surprise", "VTI", "buy", "0.299212", "317.50", 9, 35)])
    with Session(desk.engine) as s:
        out = fills_router.resync_all(None, s)
    assert out["saved"] == 0
    assert [f[0] for f in desk.fills()] == ["robinhood:r1"]
    assert desk.trades() == [("VTI", "open", Decimal("0.299212"), None)]


def test_the_background_resync_job_keeps_written_fills_too(desk, monkeypatch):
    from app.models import JobRun
    from app.routers import sync
    desk.stock(recurring_vti())
    desk.at(9, 36).poll()
    desk.at(9, 40).emails(email("m-other", "MU", "buy_to_open", 2, 193, 9, 39, **MU))
    monkeypatch.setattr(gmail_poller, "poll_new_fills", lambda **_kw: [email("m-other", "MU", "buy_to_open", 2, 193, 9, 39, **MU)])
    with Session(desk.engine) as s:
        job = JobRun(job_type="resync_all", status="running", params_json=json.dumps({"confirmed_database": "local"}))
        s.add(job)
        s.commit()
        sync._run_resync_all(s, job.id)
    assert [f[0] for f in desk.fills()] == ["robinhood:r1", "m-other"]
    assert ("VTI", "open", Decimal("0.299212"), None) in desk.trades()


# --------------------------------------------------------------------------- atomic passes, restart, switches

def test_a_pass_that_fails_part_way_leaves_nothing_behind_and_the_next_one_records_once(desk, monkeypatch):
    desk.stock(recurring_vti())
    real = fills_router._rebuild_trades

    def boom(*_a, **_kw):
        raise RuntimeError("stopped mid-pass")

    monkeypatch.setattr(fills_router, "_rebuild_trades", boom)
    with pytest.raises(RuntimeError):
        desk.at(9, 36).poller.run_once()
    assert desk.fills() == [] and desk.outcomes() == {}
    with Session(desk.engine) as s:
        assert s.exec(select(RobinhoodExecution)).all() == []
    monkeypatch.setattr(fills_router, "_rebuild_trades", real)
    desk.poller = desk.new_poller()
    desk.at(9, 37).poll()
    assert [f[0] for f in desk.fills()] == ["robinhood:r1"] and len(desk.trades()) == 1


def test_off_makes_no_call_and_the_feed_off_makes_no_call(desk, engine):
    desk.mode = "off"
    desk.stock(recurring_vti())
    assert desk.poll()["state"] == "off"
    desk.mode = "on"
    desk.feed._settings = lambda: rb.Settings(enabled=False, token_file=None, accounts=())
    assert desk.poll()["state"] == "feed off or signed out"
    assert desk.fake.calls == [] and desk.fills() == [] and desk.outcomes() == {}


def test_mode_reads_its_switch(monkeypatch):
    for value, expected in ((None, "off"), ("", "off"), ("false", "off"), ("shadow", "shadow"), ("SHADOW", "shadow"),
                            ("true", "on"), ("yes", "off")):
        if value is None:
            monkeypatch.delenv("ROBINHOOD_FILLS_ENABLED", raising=False)
        else:
            monkeypatch.setenv("ROBINHOOD_FILLS_ENABLED", value)
        assert rf.mode() == expected


# --------------------------------------------------------------------------- a day of trading, both routes

def a_day(desk):
    """Several option buys and sells, a partial fill, a fractional stock sale and a recurring buy (Roth IRA)."""
    nvda = dict(kind="call", strike="200", expiry="2026-11-21")
    partial = option_order("o4", "NVDA", [execution("o4a", "3.50000000", "1.00000", utc(13, 10))], side="sell", effect="close",
                           strike="200.0000", expiry="2026-11-21", quantity="3.00000", state="partially_filled")
    orders = [
        ("09:36", lambda: desk.stock(recurring_vti())),
        ("10:05", lambda: desk.option(mu_buy("o1", "2.00000", "1.93000000", 10, 5))),
        ("10:31", lambda: desk.option(option_order("o2", "MU", [execution("o2a", "2.40000000", "2.00000", utc(10, 31, 4))],
                                                   side="sell", effect="close"))),
        ("11:00", lambda: desk.option(option_order("o3", "NVDA", [execution("o3a", "3.10000000", "1.00000", utc(11, 0, 5)),
                                                                  execution("o3b", "3.12000000", "2.00000", utc(11, 0, 40))],
                                                   strike="200.0000", expiry="2026-11-21"))),
        ("13:10", lambda: desk.option(partial)),
        ("13:40", lambda: (partial["legs"][0]["executions"].append(execution("o4b", "3.60000000", "2.00000", utc(13, 40))),
                           partial.update(state="filled"))),
        ("14:49", lambda: desk.stock(equity_order("e5", "RKLB", [execution("e5a", "67.220000", "3.000000", utc(14, 49, 37.5)),
                                                                execution("e5b", "67.220000", "0.069042", utc(14, 49, 37.5))],
                                                  side="sell"))),
    ]
    emails = [
        ("10:07", email("m1", "MU", "buy_to_open", 2, 193, 10, 5, **MU)),
        ("10:33", email("m2", "MU", "sell_to_close", 2, 240, 10, 31, **MU)),
        ("11:02", email("m3", "NVDA", "buy_to_open", 3, 311, 11, 0, **nvda)),
        ("13:42", email("m4", "NVDA", "sell_to_close", 3, 357, 13, 40, **nvda)),
        ("14:52", email("m5", "RKLB", "sell", "3.069042", "67.22", 14, 49)),
    ]
    return orders, emails


def run_day(desk, route: str):
    """``route``: interleaved (each poll a minute after each order, emails as they come), emails_first (every email
    before any poll), poll_first (every order and poll before any email)."""
    orders, emails = a_day(desk)
    with Session(desk.engine) as s:  # the RKLB shares sold today were bought on an earlier day
        s.add(Fill(id=uuid.UUID(int=99), account_id=uuid.UUID(int=1), ticker="RKLB", instrument_type="stock", side="buy",
                   contracts=Decimal(8), price=Decimal("50.73"), executed_at=datetime(2026, 11, 2, 10, 0), raw_email_id="manual:rklb"))
        s.commit()
    hm = lambda s: tuple(int(x) for x in s.split(":"))  # noqa: E731
    events = sorted([(hm(t), 0, f) for t, f in orders] + [(hm(t), 1, e) for t, e in emails], key=lambda e: (e[0], e[1]))
    if route == "emails_first":
        for t, _k, f in [e for e in events if e[1] == 0]:
            f()
        desk.at(15, 0).emails(*[e for _t, _k, e in [x for x in events if x[1] == 1]])
        desk.at(15, 1).poll()
    elif route == "poll_first":
        for t, _k, f in [e for e in events if e[1] == 0]:
            f()
            desk.at(t[0], t[1] + 1).poll()
        desk.at(15, 0).emails(*[e for _t, _k, e in [x for x in events if x[1] == 1]])
    else:
        sent = []
        for (h, m), kind, item in events:
            if kind == 0:
                item()
                desk.at(h, m + 1).poll()
            else:
                sent.append(item)
                desk.at(h, m).emails(*sent)
    desk.at(16, 0).poll()
    desk.at(16, 5).poll()


EXPECTED_FILLS = [
    ("manual:rklb", "RKLB", "buy", Decimal("8.000000"), Decimal("50.730000"), datetime(2026, 11, 2, 10, 0)),
    ("robinhood:r1", "VTI", "buy", Decimal("0.299212"), Decimal("317.500000"), datetime(2026, 11, 12, 9, 35, 2)),
    ("m1", "MU", "buy_to_open", Decimal("2.000000"), Decimal("193.000000"), datetime(2026, 11, 12, 10, 5)),
    ("m2", "MU", "sell_to_close", Decimal("2.000000"), Decimal("240.000000"), datetime(2026, 11, 12, 10, 31)),
    ("m3", "NVDA", "buy_to_open", Decimal("3.000000"), Decimal("311.000000"), datetime(2026, 11, 12, 11, 0)),
    ("m4", "NVDA", "sell_to_close", Decimal("3.000000"), Decimal("357.000000"), datetime(2026, 11, 12, 13, 40)),
    ("m5", "RKLB", "sell", Decimal("3.069042"), Decimal("67.220000"), datetime(2026, 11, 12, 14, 49)),
]


@pytest.mark.parametrize("route", ["interleaved", "emails_first", "poll_first"])
def test_a_day_of_trading_through_both_routes_makes_one_correct_set_of_trades(desk, route):
    run_day(desk, route)
    assert desk.fills() == EXPECTED_FILLS
    outcomes = {k: (r.outcome, r.action) for k, r in desk.outcomes().items()}
    assert outcomes == {"order:r1": ("order_only", "wrote_fill"), "order:o1": ("matched", "none"), "order:o2": ("matched", "none"),
                        "order:o3": ("matched", "none"), "order:o4": ("matched", "none"), "order:e5": ("matched", "none")}
    trades = desk.trades()
    assert ("MU", "closed", Decimal("2.000000"), Decimal("94.000000")) in trades  # (240 - 193) x 2
    assert ("NVDA", "closed", Decimal("3.000000"), Decimal("138.000000")) in trades  # (357 - 311) x 3
    assert ("VTI", "open", Decimal("0.299212"), None) in trades
    assert ("RKLB", "open", Decimal("8.000000"), Decimal("50.608503")) in trades  # (67.22 - 50.73) x 3.069042, 4.930958 left


# --------------------------------------------------------------------------- off and shadow change nothing

def _dump(engine) -> str:
    with Session(engine) as s:
        tables = {
            "fill": [sorted((k, str(v)) for k, v in f.model_dump().items()) for f in s.exec(select(Fill).order_by(Fill.id)).all()],
            "trade": [sorted((k, str(v)) for k, v in t.model_dump().items()) for t in s.exec(select(Trade).order_by(Trade.id)).all()],
            "tradefill": sorted((str(tf.trade_id), str(tf.fill_id), tf.role) for tf in s.exec(select(TradeFill)).all()),
        }
    return json.dumps(tables, sort_keys=True)


@pytest.mark.parametrize("other", ["shadow", "off"])
def test_off_and_shadow_leave_fills_trades_and_pnl_byte_for_byte_unchanged(tmp_path, monkeypatch, other):
    """The full pipeline (every email imported and rebuilt as the push path does, with the poller's passes in between)
    over the same inputs, with no poller at all and with the poller ``other``: the same bytes."""
    dumps = []
    for run, current in (("none", None), (other, other)):
        counter = itertools.count(1)
        monkeypatch.setattr(fills_router.uuid, "uuid4", lambda: uuid.UUID(int=next(counter) + 1000))
        engine = create_engine(f"sqlite:///{tmp_path / f'{run}.sqlite'}")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Account(id=uuid.UUID(int=1), name="Roth IRA", type="roth_ira", last4="8267"))
            s.add(Account(id=uuid.UUID(int=2), name="Individual", type="individual", last4="8888"))
            s.commit()
        d = Desk(engine, tmp_path, monkeypatch, mode=current or "off")
        if current is None:
            d.poll = lambda: None  # no poller at all
        run_day(d, "interleaved")
        dumps.append(_dump(engine))
        if current == "shadow":
            assert d.outcomes()["order:r1"].action == "would_write_fill"
            assert sum(1 for r in d.outcomes().values() if r.outcome == "matched") == 5
        engine.dispose()
    assert dumps[0] == dumps[1]
    assert "robinhood:" not in dumps[1]


# --------------------------------------------------------------------------- masking and the owner's read

def test_no_account_number_reaches_a_row_a_log_line_or_the_owner_read(desk, caplog):
    caplog.set_level(logging.DEBUG)
    desk.stock(recurring_vti())
    desk.option(mu_buy("o1", "2.00000", "1.93000000", 10, 5))
    desk.at(10, 6).poll()
    desk.at(10, 40).poll()
    with Session(desk.engine) as s:
        out = rf.view(s)
        stored = [r.model_dump() for r in s.exec(select(RobinhoodExecution)).all()] + \
                 [r.model_dump() for r in s.exec(select(RobinhoodReconciliation)).all()]
    text = json.dumps(out, default=str) + json.dumps(stored, default=str) + caplog.text
    for number in (ROTH, INDIVIDUAL, "444447884", "33338267", "3338267"):
        assert number not in text
    assert {row["account"]["masked"] for row in out["rows"]} == {"••8267"}
    assert {row["account"]["label"] for row in out["rows"]} == {"Roth IRA"}
    assert out["counts"] == {"order_only": 2}
    first = out["rows"][0]
    assert set(first) >= {"outcome", "action", "note", "account", "order", "journal"} and first["order"]["ref"] == "o1"  # the last six characters of an id
    assert "IGNORE PREVIOUS" not in text  # Robinhood's guide text is dropped by the client


def test_the_owner_read_is_owner_only():
    from app.access_manifest import DOMAIN_ROUTES
    from app.engine import access
    route = "GET /fills/robinhood/reconciliation"
    assert route in DOMAIN_ROUTES
    granted = set().union(*(v for k, v in vars(access).items() if k.isupper() and isinstance(v, (set, frozenset))
                            and all(isinstance(x, str) for x in v)))
    assert route not in granted


def test_the_desk_says_a_new_position_s_fill_was_seen_on_robinhood(desk):
    desk.option(mu_buy("o1", "2.00000", "1.93000000", 10, 5))
    desk.at(10, 6).poll()
    with Session(desk.engine) as s:
        seen = rf.provisional(s, datetime(2026, 11, 12, 10, 6))
    assert seen == {("8267", ("MU", "call", 835.0, "2026-11-13"))}
    desk.at(10, 7).emails(email("m1", "MU", "buy_to_open", 2, 193, 10, 5, **MU))
    desk.at(10, 8).poll()
    with Session(desk.engine) as s:
        assert rf.provisional(s, datetime(2026, 11, 12, 10, 8)) == set()  # in by email: the plain join takes over
