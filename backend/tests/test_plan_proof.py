"""Does planning help? Planned against unplanned closed trades since the plan card went live: the groups, the rule at
and below its thresholds, the selection-bias caveat, Webull out, and the owner-only route. Read-only."""

from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import capture_links, plan_proof
from app.models import Account, Fill, Trade, TradeCapture, TradeFill
from app.routers import exit_habits as exit_habits_router
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary  # noqa: F401  (the shared access fixture)

ROTH = UUID(int=1)
WEBULL = UUID(int=2)
LATER = date(2099, 1, 15)
n = iter(range(100, 100_000))


def row(group, ret, day=1, peak=0.0, pnl=None):
    """One closed long option as the verdict reads it; ``ret`` is the return on premium (a fraction)."""
    opened = datetime(2026, 10, 26) + timedelta(days=day, hours=10)
    return {"id": next(n), "group": group, "pnl_pct": ret, "realized_pnl": 100 * ret if pnl is None else pnl, "day": opened.date(),
            "opened_at": opened, "closed_at": opened + timedelta(minutes=20), "hold_duration_mins": 20, "expired_worthless": False,
            "peak_pct": peak, "peak_dollars": 100.0 if peak else 0.0, "day_pnl_before": None}


def rows(group, values, count=20):
    """``count`` trades spread over ten days, cycling through ``values``."""
    return [row(group, values[i % len(values)], day=i % 10) for i in range(count)]


def test_groups_are_by_the_earliest_plan_s_timing():
    assert plan_proof.group_of("pre_entry") == "planned"
    assert plan_proof.group_of(None) == "unplanned"
    assert plan_proof.group_of("unverified") == plan_proof.group_of("retrospective") == "late"


def test_the_card_summarizes_each_group_and_states_the_caveat():
    out = plan_proof.card([row("planned", 0.5), row("planned", -0.25, pnl=-50), row("unplanned", -1.0), row("late", 0.1),
                           {**row("unplanned", 0.0), "pnl_pct": None}])
    groups = {g["key"]: g for g in out["groups"]}
    assert groups["planned"] | {"habits": None} == {
        "key": "planned", "label": "Plan saved before the entry", "in_verdict": True, "trades": 2, "counted": 2, "excluded": 0,
        "pnl": 0.0, "mean_return_pct": 12.5, "median_return_pct": 12.5, "win_rate": 0.5, "habits": None}
    assert groups["unplanned"]["excluded"] == 1 and groups["unplanned"]["mean_return_pct"] == -100.0
    assert groups["late"]["in_verdict"] is False and "not counted" in groups["late"]["label"]
    assert set(groups["planned"]["habits"]) == {"green_to_red", "held_hour_lost", "expired_worthless", "opened_green"}
    assert "Selection-biased" in out["caveat"] and "not that planning causes it" in out["caveat"]
    assert out["verdict"]["caveat"] == out["caveat"]


def test_below_twenty_in_either_group_is_not_enough_data_even_when_much_better():
    out = plan_proof.card(rows("planned", [0.5, 0.6], 19) + rows("unplanned", [-0.5, -0.4]))["verdict"]
    assert out["verdict"] == "not_enough_data" and out["reason"] == "19 planned and 20 unplanned of 20 each needed."
    # Late plans never fill the planned group.
    late = plan_proof.card(rows("late", [0.5, 0.6]) + rows("unplanned", [-0.5, -0.4]))["verdict"]
    assert late["verdict"] == "not_enough_data" and late["planned"] == 0


def test_helping_at_twenty_each_needs_two_standard_errors_and_no_more_green_to_red():
    out = plan_proof.card(rows("planned", [0.2, 0.3, 0.4]) + rows("unplanned", [-0.05, 0.05]))["verdict"]
    assert out["verdict"] == "helping" and out["difference_pct"] == 29.5 and out["days"] == 10
    assert out["se_pct"] == 2.03 and "clustered by entry day" in out["rule"] and "Selection-biased" in out["caveat"]
    # Better returns but more green-to-red closes: not called.
    planned = rows("planned", [0.2, 0.3, 0.4])
    planned[0].update(pnl_pct=-0.1, realized_pnl=-10.0, peak_pct=30.0, peak_dollars=60.0)
    mixed = plan_proof.card(planned + rows("unplanned", [-0.05, 0.05]))["verdict"]
    assert mixed["verdict"] == "not_enough_data" and "green to red more often" in mixed["reason"]


def test_not_helping_when_worse_by_the_same_margin_and_a_small_gap_is_not_called():
    worse = plan_proof.card(rows("planned", [-0.05, 0.05]) + rows("unplanned", [0.2, 0.3, 0.4]))["verdict"]
    assert worse["verdict"] == "not_helping" and worse["difference_pct"] == -29.5
    close = plan_proof.card(rows("planned", [-0.2, 0.0, 0.25]) + rows("unplanned", [-0.25, 0.2]))["verdict"]
    assert close["verdict"] == "not_enough_data" and "inside 2 standard errors" in close["reason"]


@pytest.mark.parametrize("diff, called", [(0.2, "helping"), (0.1999, "not_enough_data"), (-0.2, "not_helping"),
                                          (-0.1999, "not_enough_data")])
def test_the_margin_is_two_standard_errors_inclusive(monkeypatch, diff, called):
    monkeypatch.setattr(plan_proof, "clustered_difference", lambda planned, unplanned: (diff, 0.1, 10))
    assert plan_proof.card(rows("planned", [0.1]) + rows("unplanned", [0.1]))["verdict"]["verdict"] == called


def test_the_standard_error_is_clustered_by_entry_day():
    """Two days. Trades that move together on a day cancel; trades that move apart widen the error."""
    a, b = date(2026, 10, 26), date(2026, 10, 27)
    together = plan_proof.clustered_difference([{"day": a, "pnl_pct": 0.1}, {"day": b, "pnl_pct": 0.3}],
                                               [{"day": a, "pnl_pct": 0.0}, {"day": b, "pnl_pct": 0.2}])
    assert together[0] == pytest.approx(0.1) and together[1] == pytest.approx(0.0) and together[2] == 2
    apart = plan_proof.clustered_difference([{"day": a, "pnl_pct": 0.1}, {"day": b, "pnl_pct": 0.3}],
                                            [{"day": a, "pnl_pct": 0.2}, {"day": b, "pnl_pct": 0.0}])
    assert apart[0] == pytest.approx(0.1) and apart[1] == pytest.approx(0.2)  # sqrt(2/1 * (0.1² + 0.1²))
    single = [{**r, "day": a} for r in rows("planned", [0.3, 0.4]) + rows("unplanned", [0.0, 0.1])]
    assert "one day" in plan_proof.card(single)["verdict"]["reason"]


# ------------------------------------------------------------------ database + endpoint

@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        session.add(Account(id=WEBULL, name="Webull", type="individual", last4="2222", broker="webull"))
        session.commit()
        yield session
    engine.dispose()


def closed_trade(db, opened: str, strike: float, entry=1.0, exit=1.5, account=ROTH) -> Trade:
    """One NVDA call bought at a New York wall clock and sold 30 minutes later, rebuilt into its own trade."""
    i = next(n)
    at = datetime.fromisoformat(opened)
    for j, (side, price, when) in enumerate((("buy_to_open", entry, at), ("sell_to_close", exit, at + timedelta(minutes=30)))):
        db.add(Fill(id=UUID(int=i * 10 + j), account_id=account, ticker="NVDA", instrument_type="option", side=side, contracts=1,
                    price=price, executed_at=when, raw_email_id=f"proof:{i}:{j}", option_type="call", strike=strike, expiration=LATER))
    db.commit()
    _rebuild_trades(db, "test")
    db.commit()
    return db.get(Trade, db.exec(select(TradeFill).where(TradeFill.fill_id == UUID(int=i * 10))).one().trade_id)


def plan(db, trade: Trade, minutes_before: int, strike: float) -> None:
    """A plan received ``minutes_before`` the entry (negative: after it), linked to ``trade``. EDT is UTC-4."""
    received = trade.opened_at + timedelta(hours=4) - timedelta(minutes=minutes_before)
    capture = TradeCapture(client_id=f"client-{next(n)}", received_at=received, account_id=trade.account_id, account_label="Roth",
                           underlying="NVDA", side="buy_calls", instrument="option", mode="template", strike=strike, expiration=LATER,
                           context_state="unavailable", image_state="unavailable")
    db.add(capture)
    db.commit()
    db.refresh(capture)
    capture_links.link(db, capture, trade.id)


def test_the_endpoint_groups_robinhood_trades_since_go_live_and_leaves_webull_out(db):
    planned = closed_trade(db, "2026-10-26T10:00", 100, exit=2.0)
    plan(db, planned, 5, 100)
    late = closed_trade(db, "2026-10-26T11:00", 110)
    plan(db, late, -3, 110)
    closed_trade(db, "2026-10-26T12:00", 120, exit=0.5)  # no plan
    closed_trade(db, "2026-10-26T13:00", 130, account=WEBULL)  # Webull: out
    old = closed_trade(db, "2026-10-23T10:00", 140)  # before the plan card: out
    plan(db, old, 5, 140)
    before = [(t.id, float(t.realized_pnl)) for t in db.exec(select(Trade)).all()]

    app = FastAPI()
    app.include_router(exit_habits_router.router, prefix="/analytics")
    app.dependency_overrides[get_session] = lambda: db
    body = TestClient(app).get("/analytics/plan-proof").json()
    assert [(t.id, float(t.realized_pnl)) for t in db.exec(select(Trade)).all()] == before  # read-only

    groups = {g["key"]: g for g in body["groups"]}
    assert (body["go_live"], body["trades"]) == ("2026-10-25", 3)
    assert (groups["planned"]["trades"], groups["planned"]["mean_return_pct"], groups["planned"]["pnl"]) == (1, 100.0, 1.0)
    assert (groups["unplanned"]["trades"], groups["unplanned"]["mean_return_pct"], groups["unplanned"]["win_rate"]) == (1, -50.0, 0.0)
    assert groups["late"]["trades"] == 1
    assert body["verdict"]["verdict"] == "not_enough_data" and body["verdict"]["reason"] == "1 planned and 1 unplanned of 20 each needed."
    assert "Selection-biased" in body["caveat"]


def test_owner_only(boundary):  # noqa: F811
    assert boundary.owner.get("/analytics/plan-proof").status_code == 200
    assert boundary.public.get("/analytics/plan-proof").status_code == 401


def test_journal_readers_are_denied(boundary):  # noqa: F811
    from tests.test_browser_access import signin

    boundary.patch.setenv("TJ_ACCESS_SAMPLE_DATA", "true")
    created = boundary.owner.post("/access/assistants", json={"identifier": "reader",
        "grants": {"symbols": ["SPY"], "run_ids": [], "journal_read": True}})
    assert signin(boundary, identifier="reader", key=created.json()["key"]).status_code == 200
    assert boundary.public.get("/stats/analytics").status_code == 200  # the journal grant is real
    assert boundary.public.get("/analytics/plan-proof").status_code == 403
