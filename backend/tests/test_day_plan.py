"""The pre-market plan card (app/engine/day_plan.py): a max size and an exit time saved for the day, and the pings that
hold him to them."""
from datetime import UTC, date, datetime
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import day_plan, notification_policy, phone
from app.models import Account, DayJournalEntry, Fill, Trade, TradeFill

ROTH = uuid.UUID("00000000-0000-4000-8000-000000000001")
WEBULL = uuid.UUID("00000000-0000-4000-8000-000000000002")
DAY = date(2026, 11, 24)


def at(hour: int, minute: int = 0) -> float:
    """Epoch of a New York (EST) wall clock on Nov 24."""
    return datetime(2026, 11, 24, hour + 5, minute, tzinfo=UTC).timestamp()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker=None))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="1111", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


def option(db, ticker, contracts, price, hour, minute=0, status="open", account=ROTH):
    opened = datetime(2026, 11, 24, hour, minute)
    trade = Trade(account_id=account, ticker=ticker, instrument_type="option", contracts=contracts, option_type="call", strike=100,
                  expiration=DAY, avg_entry_premium=price, total_premium_paid=contracts * price, opened_at=opened, status=status)
    db.add(trade)
    db.flush()
    fill = Fill(account_id=account, ticker=ticker, instrument_type="option", side="buy_to_open", contracts=contracts, price=price,
                executed_at=opened, raw_email_id=f"{ticker}-{uuid.uuid4().hex[:8]}", option_type="call", strike=100, expiration=DAY)
    db.add(fill)
    db.flush()
    db.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="entry"))
    db.commit()
    return trade


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(phone, "configured", lambda: True)
    monkeypatch.setattr(phone, "send", lambda title, body, **kw: out.append((kw["kind"], title, body)) or ("r", "none"))
    return out


def test_a_plan_is_saved_as_a_day_journal_entry_and_the_newest_wins(engine):
    with Session(engine) as db:
        assert day_plan.plan_for(db, DAY) is None
        day_plan.save(db, DAY, 500, "11:30", "op-1")
        plan = day_plan.save(db, DAY, 400, None, "op-2")
        assert (plan["max_usd"], plan["exit_by"]) == (400, None)
        assert day_plan.plan_for(db, DAY)["max_usd"] == 400
        assert day_plan.save(db, DAY, 400, None, "op-2")["max_usd"] == 400  # a retried save is the same entry
        row = db.exec(select(DayJournalEntry).where(DayJournalEntry.operation_id == "op-1")).one()
        assert (row.kind, row.text) == ("day_plan", "Day plan: max $500 a position, out of today's options by 11:30 AM ET")


@pytest.mark.parametrize("max_usd, exit_by", [(None, None), (0, None), (-5, None), (None, "9:30"), (None, "24:00"), (2_000_000, None)])
def test_a_plan_needs_a_positive_size_or_a_24_hour_time(engine, max_usd, exit_by):
    with Session(engine) as db, pytest.raises(day_plan.PlanError):
        day_plan.save(db, DAY, max_usd, exit_by, "op")


def test_over_size_late_and_exit_time_each_ping_once(engine, sent, monkeypatch):
    with Session(engine) as db:
        day_plan.save(db, DAY, 500, "11:30", "op")
        option(db, "NVDA", 3, 250, 9, 45)  # $750: over by $250
        option(db, "AMD", 1, 400, 10, 0)  # inside the plan, still open at 11:30
        option(db, "MU", 2, 300, 10, 5, status="closed")  # $600 over, but closed: the size ping still says so
        option(db, "TSLA", 5, 200, 9, 50, account=WEBULL)  # Webull is left out
    clock = [at(10, 10)]
    pings = day_plan.DayPlanPings(engine, clock=lambda: clock[0])
    pings.run()
    assert [(k, t) for k, t, _ in sent] == [("plan_size", "NVDA: $750 in, over your $500 max"), ("plan_size", "MU: $600 in, over your $500 max")]
    assert "$250 over the max size" in sent[0][2]
    sent.clear()
    with Session(engine) as db:
        option(db, "SPY", 1, 100, 11, 40)  # opened after the exit time
    clock[0] = at(11, 45)
    pings.run()
    assert [k for k, _, _ in sent] == ["plan_late", "plan_exit"]
    assert sent[1][1] == "11:30 AM: your exit time, 2 still open"
    assert "NVDA" in sent[1][2] and "AMD" in sent[1][2] and "SPY" not in sent[1][2]
    sent.clear()
    clock[0] = at(11, 50)
    day_plan.DayPlanPings(engine, clock=lambda: clock[0]).run()  # a restart: the policy's claims hold
    assert sent == []


def test_no_plan_no_pings_and_nothing_outside_the_session(engine, sent):
    with Session(engine) as db:
        option(db, "NVDA", 30, 250, 9, 45)
    day_plan.DayPlanPings(engine, clock=lambda: at(10)).run()
    with Session(engine) as db:
        day_plan.save(db, DAY, 100, "09:00", "op")
    day_plan.DayPlanPings(engine, clock=lambda: at(8)).run()  # before the open
    assert sent == []


def test_the_pings_are_loud_and_off_by_default(monkeypatch):
    monkeypatch.delenv("DAY_PLAN_ALERTS", raising=False)
    assert not day_plan.enabled()
    assert all(phone.loud(k) for k in ("plan_size", "plan_exit", "plan_late"))
    assert notification_policy._label("plan_exit") == "day plan exit time"


def test_a_ticker_he_hid_on_the_desk_is_left_out(engine, sent):
    from app.engine import day_journal
    with Session(engine) as db:
        day_plan.save(db, DAY, 500, "11:30", "op")
        option(db, "NVDA", 3, 250, 9, 45)  # over size, but hidden
        option(db, "AMD", 1, 400, 10, 0)
        day_journal.append(db, day=DAY, operation_id="hide", kind="follow", symbol="NVDA", text="Not following")
    day_plan.DayPlanPings(engine, clock=lambda: at(11, 45)).run()
    assert [(k, t) for k, t, _ in sent] == [("plan_exit", "11:30 AM: your exit time, 1 still open")]
    assert "NVDA" not in sent[0][2]
