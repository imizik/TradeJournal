"""The weekly review: the three exit leaks, the rule chosen for next week, its
check against later trades, and evidence that survives a rebuild. No model call."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete, select

from app.database import get_session
from app.engine import weekly_review
from app.models import Account, Fill, Trade, TradeFill, TradePathMetrics, WeeklyReviewRecord
from app.routers.weekly_review import router

ROTH, WEBULL = UUID(int=1), UUID(int=2)
WEEK = date(2026, 10, 12)  # a Monday
NEXT = WEEK + timedelta(days=7)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Account(id=ROTH, name="Roth IRA", type="roth_ira", last4="0001", broker="robinhood"),
                         Account(id=WEBULL, name="Webull", type="individual", last4="0002", broker="webull")])
        session.commit()
    yield engine
    engine.dispose()


def trade(n, opened, closed, pnl, *, account=ROTH, premium=500, status="closed", expiration=date(2026, 11, 20), mfe=None,
          instrument="option", key=None):
    """A trade, its first entry fill (same ID, as the reconstructor makes it) and optional path metrics."""
    trade_id = UUID(int=100 + n)
    rows = [Trade(id=trade_id, account_id=account, ticker="SPY", instrument_type=instrument, option_type="call", strike=600,
                  expiration=expiration if instrument == "option" else None, contracts=1, avg_entry_premium=premium / 100,
                  total_premium_paid=premium, realized_pnl=None if pnl is None else Decimal(str(pnl)), opened_at=opened,
                  closed_at=closed, status=status),
            Fill(id=trade_id, account_id=account, raw_email_id=key or f"mail-{n}", ticker="SPY", instrument_type=instrument,
                 side="buy_to_open", contracts=1, price=premium / 100, executed_at=opened, option_type="call", strike=600,
                 expiration=expiration if instrument == "option" else None),
            TradeFill(trade_id=trade_id, fill_id=trade_id, role="entry")]
    if mfe is not None:
        rows.append(TradePathMetrics(trade_id=trade_id, data_source="test", fetched_at=closed or opened, option_mfe_pct=mfe))
    return rows


def seed(engine, *groups):
    with Session(engine) as session:
        for group in groups:
            session.add_all(group)
        session.commit()


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute)


def test_the_three_leaks_count_closed_option_trades_in_the_week(engine):
    seed(engine,
         trade(1, at(13, 9, 40), at(13, 10), -50, mfe=25),  # reached +25%, closed red; held 20 minutes
         trade(2, at(13, 10), at(13, 12, 30), -120),  # no price path; held 2.5 hours
         trade(3, at(14, 10), at(16, 16), -500, status="expired", expiration=date(2026, 10, 16), mfe=5),
         trade(4, at(15, 9, 45), at(15, 10, 30), 200, mfe=40),  # a winner that stayed green
         trade(5, at(9, 10), at(9, 11), -900, mfe=30),  # closed the week before
         trade(6, at(13, 10), at(13, 12), -700, account=WEBULL, mfe=50),  # Webull is out of scope
         trade(7, at(13, 10), at(13, 12), -400, instrument="stock"),  # options only
         trade(8, datetime(2026, 10, 14), datetime(2026, 10, 14), -60, mfe=2))  # a date without a time of day
    with Session(engine) as session:
        view = weekly_review.view(session, WEEK)
    assert view["summary"] == {"trades": 5, "pnl": -530.0, "wins": 1, "losses": 4}
    assert view["coverage"] == {"trades": 5, "with_path": 4, "accounts": ["Roth IRA"]}
    leaks = {row["key"]: row for row in view["leaks"]}
    assert (leaks["winner_to_red"]["count"], leaks["winner_to_red"]["pnl"], leaks["winner_to_red"]["unmeasured"]) == (1, -50.0, 1)
    assert [row["trade_id"] for row in leaks["winner_to_red"]["trades"]] == [str(UUID(int=101))]
    # Trade 3 was held over two days; trade 8 has no time of day, so its hold can't be measured.
    assert (leaks["held_hour_red"]["count"], leaks["held_hour_red"]["pnl"], leaks["held_hour_red"]["unmeasured"]) == (2, -620.0, 1)
    assert (leaks["expiry_day"]["count"], leaks["expiry_day"]["pnl"]) == (1, -500.0)
    assert view["previous"] is None and view["chosen"] is None and view["history"] == []


@pytest.mark.parametrize("rule,kwargs,pnl,expected", [
    ("winner_to_red", {"mfe": 9.9}, -10, "untested"),
    ("winner_to_red", {"mfe": 10}, -10, "broke"),
    ("winner_to_red", {"mfe": 10}, 0, "kept"),
    ("winner_to_red", {}, 60, "kept"),  # closed up 12%, so it got past 10% without a path
    ("winner_to_red", {}, 20, "untested"),
    ("expiry_day", {"expiration": date(2026, 10, 13)}, -449, "kept"),  # closed on its last day down under 90%
    ("expiry_day", {"expiration": date(2026, 10, 13)}, -450, "broke"),
    ("expiry_day", {"expiration": date(2026, 10, 14)}, -500, "untested"),  # out before the last day
])
def test_each_rule_judges_one_trade(rule, kwargs, pnl, expected):
    rows = trade(1, at(13, 10), at(13, 10, 30), pnl, **kwargs)
    path = rows[3] if len(rows) == 4 else None
    assert weekly_review.judge(rule, weekly_review.RULES[rule]["params"], rows[0], path) == expected


def test_suggested_result_needs_three_tested_trades_unless_one_broke():
    assert [weekly_review.suggest(t, b) for t, b in [(0, 0), (2, 0), (3, 0), (1, 1), (4, 1)]] == \
        ["not_enough", "not_enough", "kept", "broken", "partly"]


def test_the_chosen_rule_is_checked_next_week_and_its_evidence_survives_a_rebuild(engine):
    with Session(engine) as session:
        weekly_review.choose(session, WEEK, "winner_to_red", "  scale out at +10  ")
        record = session.exec(select(WeeklyReviewRecord)).one()
        record.chosen_at = datetime(2026, 10, 17, 21)  # Saturday 17:00 New York
        session.add(record)
        session.commit()
    seed(engine,
         trade(11, at(17, 16), at(19, 10), -80, mfe=50),  # entered before the rule was chosen
         trade(12, at(19, 9, 40), at(19, 10, 30), -90, mfe=15),  # broke it
         trade(13, at(20, 9, 50), at(20, 10, 10), 150, mfe=20),  # kept it
         trade(14, at(21, 10), at(21, 10, 20), -40, mfe=4),  # never got to +10%
         trade(15, at(22, 10), None, None, status="open"),  # still open
         trade(16, at(23, 10), at(23, 11), -30))  # no path
    with Session(engine) as session:
        view = weekly_review.view(session, NEXT)
        prior = view["previous"]
        assert (prior["rule_key"], prior["note"], prior["params"]) == ("winner_to_red", "scale out at +10", {"peak_pct": 10})
        found = prior["check"]
        assert (found["entered"], found["closed"], found["tested"], found["broke"], found["unmeasured"], found["suggested"]) == (5, 4, 2, 1, 1, "partly")
        assert [(row["trade_id"], row["state"]) for row in found["trades"]] == \
            [(str(UUID(int=112)), "broke"), (str(UUID(int=113)), "kept"), (str(UUID(int=116)), "unmeasured")]
        assert [row["trade_id"] for row in found["still_open"]] == [str(UUID(int=115))]
        assert found["frozen"] is False and "anchors" not in found

        weekly_review.confirm(session, NEXT, "broken")
        record = session.exec(select(WeeklyReviewRecord).where(WeeklyReviewRecord.week_start == WEEK)).one()
        assert (record.result, record.result_source) == ("broken", "changed")
        with pytest.raises(weekly_review.ReviewError, match="already been checked"):
            weekly_review.choose(session, WEEK, "expiry_day", None)

        # A resync: every fill and trade is recreated with new IDs, and trade 13's fill is gone.
        session.exec(delete(TradePathMetrics))
        session.exec(delete(TradeFill))
        session.exec(delete(Trade))
        session.exec(delete(Fill))
        session.commit()
    rebuilt = trade(40, at(19, 9, 40), at(19, 10, 30), -90, mfe=15, key="mail-12")
    seed(engine, rebuilt, trade(41, at(20, 11), at(20, 11, 30), 75, mfe=30))  # a later trade the frozen check ignores
    with Session(engine) as session:
        found = weekly_review.view(session, NEXT)["previous"]["check"]
        assert found["frozen"] is True and (found["tested"], found["broke"], found["suggested"]) == (2, 1, "partly")
        assert [row["trade_id"] for row in found["trades"]] == [str(UUID(int=140)), None, None]
        assert [row["contract"] for row in found["still_open"]] == ["SPY 11/20/26 600C"]
        # Changing only the confirmed label keeps the frozen evidence.
        weekly_review.confirm(session, NEXT, "partly")
        record = session.exec(select(WeeklyReviewRecord).where(WeeklyReviewRecord.week_start == WEEK)).one()
        assert (record.result, record.result_source) == ("partly", "suggested")
        assert json.loads(record.evidence_json)["tested"] == 2


def test_skip_keep_and_change_a_rule(engine):
    with Session(engine) as session:
        weekly_review.choose(session, WEEK, None, None)
        view = weekly_review.view(session, NEXT)
        assert view["previous"]["rule_key"] is None and "check" not in view["previous"]
        with pytest.raises(weekly_review.ReviewError, match="No rule"):
            weekly_review.confirm(session, NEXT, "kept")

        first = weekly_review.choose(session, NEXT, "held_hour_red", None)
        chosen_at = first.chosen_at
        same = weekly_review.choose(session, NEXT, "held_hour_red", "note added later")
        assert same.chosen_at == chosen_at  # editing the note does not restart the practice window
        changed = weekly_review.choose(session, NEXT, "expiry_day", None)
        assert changed.chosen_at >= chosen_at and json.loads(changed.rule_params_json) == {"loss_pct": 90}
        history = weekly_review.view(session, NEXT + timedelta(days=7))["history"]
        assert [(row["week_start"], row["rule_key"]) for row in history] == [(NEXT.isoformat(), "expiry_day"), (WEEK.isoformat(), None)]
        with pytest.raises(weekly_review.ReviewError, match="Unknown rule"):
            weekly_review.choose(session, WEEK, "trend_aligned", None)


def test_routes_validate_the_week_and_save_through_reload(engine):
    app = FastAPI()
    app.include_router(router, prefix="/weekly-review")

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    client = TestClient(app)
    assert client.get("/weekly-review/2026-10-13").status_code == 400  # a Tuesday
    assert client.get(f"/weekly-review/{weekly_review.this_monday() + timedelta(days=7)}").status_code == 400
    assert client.get("/weekly-review/not-a-date").status_code == 400
    saved = client.put(f"/weekly-review/{WEEK}", json={"rule_key": "winner_to_red"})
    assert saved.status_code == 200 and saved.json()["chosen"]["rule_key"] == "winner_to_red"
    assert client.get(f"/weekly-review/{WEEK}").json()["chosen"]["rule_text"] == weekly_review.RULES["winner_to_red"]["text"]
    assert client.put(f"/weekly-review/{WEEK}", json={"rule_key": "nope"}).status_code == 409
    confirmed = client.put(f"/weekly-review/{NEXT}/result", json={"result": "not_enough"})
    assert confirmed.status_code == 200 and confirmed.json()["previous"]["result"] == "not_enough"
    assert client.put(f"/weekly-review/{NEXT}/result", json={"result": "great"}).status_code == 409
