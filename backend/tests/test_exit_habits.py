"""Exit habits: what happened after each phone alert, and the audit's four exit habits vs. baseline. Read-only."""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import reconstructor
from app.engine.chart_math import ET
from app.engine.exit_habits import follow_up, habit_flags, scorecard, verdict
from app.models import Account, Fill, FillMarketContext, PositionAlert, Trade, TradeFill, TradePathMetrics
from app.routers import exit_habits as exit_habits_router
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary  # noqa: F401  (the shared access fixture)

ROTH = UUID(int=1)
WED = date(2026, 10, 21)
n = iter(range(100, 100_000))


def utc(when: str) -> datetime:
    """An ET wall-clock time as the naive UTC that position_alert stores."""
    return datetime.fromisoformat(when).replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)


def f(side, qty, price, when):
    return {"id": next(n), "side": side, "contracts": qty, "price": price, "executed_at": datetime.fromisoformat(when)}


def alert(when="2026-10-21T10:30", contracts=2, mark=300.0):
    return {"detected_at": utc(when), "contracts": contracts, "mark": mark}


BUY = [f("buy_to_open", 2, 200.0, "2026-10-21T09:45")]


# ------------------------------------------------------------------ follow-up

def test_closed_within_fifteen_minutes_and_the_result_against_the_mark():
    out = follow_up(alert(), BUY + [f("sell_to_close", 2, 280.0, "2026-10-21T10:40")], "closed")
    assert out["response"] == "closed_15m"
    # Sold 2 at $280 against a $300 mark at the alert: closing at the alert was $40 better.
    assert (out["realized_after"], out["value_at_alert"], out["vs_alert"]) == (560.0, 600.0, -40.0)


def test_a_partial_trim_within_fifteen_minutes():
    fills = BUY + [f("sell_to_close", 1, 320.0, "2026-10-21T10:35"), f("sell_to_close", 1, 250.0, "2026-10-21T14:00")]
    out = follow_up(alert(), fills, "closed")
    assert out["response"] == "trimmed_15m" and out["vs_alert"] == 320 + 250 - 600


def test_a_trim_with_the_rest_still_open_has_no_result_yet():
    out = follow_up(alert(), BUY + [f("sell_to_close", 1, 320.0, "2026-10-21T10:35")], "open")
    assert out["response"] == "trimmed_15m" and out["vs_alert"] is None and "Still open" in out["note"]


def test_closed_later_the_same_day():
    out = follow_up(alert(), BUY + [f("sell_to_close", 2, 350.0, "2026-10-21T15:50")], "closed")
    assert out["response"] == "closed_later" and out["vs_alert"] == 100.0


def test_held_overnight():
    out = follow_up(alert(), BUY + [f("sell_to_close", 2, 150.0, "2026-10-22T09:35")], "closed")
    assert out["response"] == "held_overnight" and out["vs_alert"] == -300.0


def test_expired_counts_the_unsold_contracts_at_zero():
    out = follow_up(alert(contracts=2, mark=40.0), BUY, "expired")
    assert out["response"] == "expired" and out["realized_after"] == 0.0 and out["vs_alert"] == -80.0


def test_still_open():
    out = follow_up(alert(), BUY, "open")
    assert out["response"] == "still_open" and out["vs_alert"] is None


def test_contracts_bought_after_the_alert_sit_behind_the_alerted_ones():
    """First in, first out: the first two sold after the alert are the alert's, whatever is bought later."""
    fills = BUY + [f("buy_to_open", 3, 100.0, "2026-10-21T10:32"), f("sell_to_close", 2, 310.0, "2026-10-21T10:41"),
                   f("sell_to_close", 3, 90.0, "2026-10-22T10:00")]
    out = follow_up(alert(), fills, "closed")
    assert out["response"] == "closed_15m" and out["vs_alert"] == 20.0


def test_a_sale_in_the_alerts_own_minute_counts_as_after_when_the_open_count_says_so():
    """The broker's fill minute is 10:30 and the alert fired at 10:30:40: two were still open at the alert."""
    fills = BUY + [f("sell_to_close", 2, 290.0, "2026-10-21T10:30")]
    out = follow_up(alert("2026-10-21T10:30:40"), fills, "closed")
    assert out["response"] == "closed_15m" and out["vs_alert"] == -20.0


def test_a_missing_mark_leaves_the_result_null():
    out = follow_up(alert(mark=None), BUY + [f("sell_to_close", 2, 280.0, "2026-10-21T10:40")], "closed")
    assert out["response"] == "closed_15m" and out["realized_after"] == 560.0
    assert out["vs_alert"] is None and "no midpoint" in out["note"]


def test_unmatched_fills_are_never_guessed():
    assert follow_up(alert(), None, None)["note"].startswith("The position's fills could not be found")
    out = follow_up(alert(contracts=5), BUY, "open")  # the alert saw 5 open; the fills show 2
    assert out["response"] is None and out["vs_alert"] is None and "no longer show" in out["note"]


# ------------------------------------------------------------------ habits

def trade(i, pnl, closed="2026-10-10T15:00", opened=None, hold=30, expired=False, peak_pct=None, peak_dollars=None, day=None):
    closed_at = datetime.fromisoformat(closed)
    return {"id": i, "realized_pnl": pnl, "closed_at": closed_at, "opened_at": datetime.fromisoformat(opened) if opened else closed_at,
            "hold_duration_mins": hold, "expired_worthless": expired, "peak_pct": peak_pct, "peak_dollars": peak_dollars,
            "day_pnl_before": day}


def test_green_to_red_needs_ten_percent_and_fifty_dollars_then_red():
    assert habit_flags(trade(1, -10, peak_pct=12, peak_dollars=60))["green_to_red"] is True
    assert habit_flags(trade(2, -10, peak_pct=12, peak_dollars=40))["green_to_red"] is False  # under $50
    assert habit_flags(trade(3, -10, peak_pct=8, peak_dollars=200))["green_to_red"] is False  # under 10%
    assert habit_flags(trade(4, 5, peak_pct=30, peak_dollars=200))["green_to_red"] is False  # closed green
    assert habit_flags(trade(5, -10))["green_to_red"] is None  # no path metrics


def test_held_an_hour_to_a_same_day_red_close():
    assert habit_flags(trade(1, -50, opened="2026-10-10T10:00", hold=300))["held_hour_lost"] is True
    assert habit_flags(trade(2, -50, opened="2026-10-10T14:30", hold=30))["held_hour_lost"] is False
    assert habit_flags(trade(3, -50, opened="2026-10-09T15:00", hold=1440))["held_hour_lost"] is False  # overnight
    assert habit_flags(trade(4, 50, opened="2026-10-10T10:00", hold=300))["held_hour_lost"] is False
    assert habit_flags(trade(5, -50, hold=None))["held_hour_lost"] is None


def test_expired_and_opened_green():
    assert habit_flags(trade(1, -300, expired=True))["expired_worthless"] is True
    assert habit_flags(trade(2, -300))["expired_worthless"] is False
    assert habit_flags(trade(3, 10, day=120.0))["opened_green"] is True
    assert habit_flags(trade(4, 10, day=0.0))["opened_green"] is False
    assert habit_flags(trade(5, 10, day=-40.0))["opened_green"] is False
    assert habit_flags(trade(6, 10))["opened_green"] is None


def test_fewer_than_thirty_since_the_alerts_and_exclusions():
    base = [trade(i, -100, closed="2026-10-10T15:00", expired=True, day=50.0) for i in range(3)] + [trade(9, 200, closed="2026-10-20T15:00")]
    recent = [trade(10, -40, closed="2026-10-21T11:00", expired=True), trade(11, 60, closed="2026-10-22T11:00", day=10.0)]
    out = scorecard(base + recent, go_live=WED)
    assert (out["since_go_live"], out["recent_trades"], out["baseline_trades"], out["window"]) == (2, 2, 4, 30)
    habits = {h["key"]: h for h in out["habits"]}
    assert habits["expired_worthless"]["baseline"] == {"n": 3, "trades": 4, "excluded": 0, "pct": 0.75, "pnl": -300.0}
    assert habits["expired_worthless"]["recent"] == {"n": 1, "trades": 2, "excluded": 0, "pct": 0.5, "pnl": -40.0}
    # Day P&L at entry is missing for one baseline and one recent trade: left out, not counted as a zero.
    assert habits["opened_green"]["baseline"] == {"n": 3, "trades": 3, "excluded": 1, "pct": 1.0, "pnl": -300.0}
    assert habits["opened_green"]["recent"] == {"n": 1, "trades": 1, "excluded": 1, "pct": 1.0, "pnl": 60.0}
    assert habits["green_to_red"]["recent"] == {"n": 0, "trades": 0, "excluded": 2, "pct": None, "pnl": 0.0}


def test_only_the_latest_thirty_since_the_alerts_are_compared():
    recent = [trade(i, -1 if i < 5 else 1, closed=f"2026-10-{21 + i // 10}T{10 + i % 10}:00", expired=i < 5) for i in range(35)]
    out = scorecard(recent, go_live=WED)
    assert (out["since_go_live"], out["recent_trades"]) == (35, 30)
    assert {h["key"]: h for h in out["habits"]}["expired_worthless"]["recent"]["n"] == 0  # the five oldest fell out


# ------------------------------------------------------------------ verdict (/proof)

def _card(base_hits: dict, recent_hits: dict, base_n=300, recent_n=30):
    """Every trade carries all four habits' data; ``*_hits`` says how many have each habit."""
    def rows(count, hits, closed):
        return [trade(i, -10 if i < hits.get("held_hour_lost", 0) else 10, closed=closed, opened=closed,
                      hold=90 if i < hits.get("held_hour_lost", 0) else 10, expired=i < hits.get("expired_worthless", 0),
                      peak_pct=20, peak_dollars=100, day=50.0 if i < hits.get("opened_green", 0) else -5.0)
                for i in range(count)]
    return scorecard(rows(base_n, base_hits, "2026-10-10T15:00") + rows(recent_n, recent_hits, "2026-10-22T15:00"), go_live=WED)


def test_verdict_with_no_trades_or_no_baseline_is_not_enough_data():
    empty = verdict(scorecard([], go_live=WED))
    assert empty["verdict"] == "not_enough_data" and "no baseline" in empty["reason"]
    only_recent = verdict(_card({}, {}, base_n=0))
    assert only_recent["verdict"] == "not_enough_data" and "no baseline" in only_recent["reason"]


def test_verdict_under_thirty_recent_trades_is_not_enough_data_even_when_better():
    out = verdict(_card({"expired_worthless": 60, "opened_green": 120}, {}, recent_n=12))
    assert out["verdict"] == "not_enough_data" and out["sample"] == 12 and "12 of 30" in out["reason"]
    assert "2 standard errors" in out["rule"]


def test_verdict_helping_needs_two_habits_clearly_lower_and_none_higher():
    # Baseline: 20% expired, 40% opened green, 30% held-hour losers; recent 30 trades have none of the first two.
    base = {"expired_worthless": 60, "opened_green": 120, "held_hour_lost": 90}
    out = verdict(_card(base, {"held_hour_lost": 9}))
    assert out["verdict"] == "helping"
    assert out["changes"] == {"green_to_red": "same", "held_hour_lost": "same", "expired_worthless": "lower", "opened_green": "lower"}
    one = verdict(_card(base, {"held_hour_lost": 9, "opened_green": 12}))  # only expirations clearly fell
    assert one["verdict"] == "not_enough_data" and "two are needed" in one["reason"]
    worse = verdict(_card(base, {"held_hour_lost": 20}))  # two lower, but held-hour losers clearly up
    assert worse["verdict"] == "not_helping" and "more frequent" in worse["reason"]
    flat = verdict(_card(base, {"expired_worthless": 6, "opened_green": 12, "held_hour_lost": 9}))
    assert flat["verdict"] == "not_helping" and "No habit" in flat["reason"]


# ------------------------------------------------------------------ database + endpoint

class _Thursday(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 23)


@pytest.fixture(autouse=True)
def on_thursday(monkeypatch):
    """Trade rebuilds expire contracts past the machine's own date; these run as of Oct 23, whatever today is."""
    monkeypatch.setattr(reconstructor, "date", _Thursday)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    yield engine
    engine.dispose()


def fill(db, ticker, side, qty, price, when, expiration=date(2026, 10, 24)):
    i = next(n)
    db.add(Fill(id=UUID(int=i), account_id=ROTH, ticker=ticker, instrument_type="option", side=side, contracts=qty, price=price,
                executed_at=datetime.fromisoformat(when), raw_email_id=f"gmail:{i}", option_type="call", strike=230, expiration=expiration))
    return f"gmail:{i}"


def add_alert(db, source, kind, when, contracts, mark, delivery="sent", contract="SNDK 10/24/26 230C"):
    db.add(PositionAlert(account_id=ROTH, source_key=source, kind=kind, generation=0, trade_id=UUID(int=0), contract=contract,
                         contracts=contracts, avg_cost=200, mark=mark, detected_at=utc(when), delivery=delivery))


def test_the_endpoint_reads_alerts_by_source_identity_and_habits(engine):
    with Session(engine) as db:
        sndk = fill(db, "SNDK", "buy_to_open", 2, 200, "2026-10-21T09:45")
        fill(db, "SNDK", "sell_to_close", 2, 280, "2026-10-21T10:40")
        mu = fill(db, "MU", "buy_to_open", 1, 100, "2026-10-21T13:00", expiration=date(2026, 10, 22))
        fill(db, "NVDA", "buy_to_open", 1, 100, "2026-10-14T10:00")
        fill(db, "NVDA", "sell_to_close", 1, 80, "2026-10-14T14:00")
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
        add_alert(db, sndk, "giveback", "2026-10-21T10:30", 2, 300.0)
        add_alert(db, mu, "hold_hour", "2026-10-21T14:00", 1, 90.0, delivery="unknown", contract="MU 10/22/26 230C")  # a kind added later
        add_alert(db, mu, "expiry_first", "2026-10-22T14:30", 1, None, delivery="expired")  # never sent: not listed
        add_alert(db, "gmail:missing", "giveback", "2026-10-20T11:00", 1, 50.0)
        nvda_trade = db.exec(select(Trade).where(Trade.ticker == "NVDA")).one()
        db.add(TradePathMetrics(trade_id=nvda_trade.id, data_source="test", fetched_at=datetime(2026, 10, 15),
                                option_mfe_pct=25.0, option_peak_unrealized_pnl=25.0))
        entry = db.exec(select(TradeFill.fill_id).where(TradeFill.trade_id == nvda_trade.id, TradeFill.role == "entry")).one()
        db.add(FillMarketContext(fill_id=entry, data_source="test", fetched_at=datetime(2026, 10, 15), realized_pnl_today_before=75.0))
        db.commit()
        before = [(t.id, float(t.realized_pnl)) for t in db.exec(select(Trade)).all()]

        app = FastAPI()
        app.include_router(exit_habits_router.router, prefix="/analytics")
        app.dependency_overrides[get_session] = lambda: db
        body = TestClient(app).get("/analytics/exit-habits").json()
        assert [(t.id, float(t.realized_pnl)) for t in db.exec(select(Trade)).all()] == before  # read-only

    sndk_trade = body["alerts"][1]["trade_id"]
    assert [(a["kind"], a["response"], a["vs_alert"]) for a in body["alerts"]] == [
        ("hold_hour", "expired", -90.0), ("giveback", "closed_15m", -40.0), ("giveback", None, None)]
    assert sndk_trade != str(UUID(int=0))  # linked to the rebuilt trade, not the stale id
    assert "could not be found" in body["alerts"][2]["note"] and body["alerts"][2]["trade_id"] is None  # no dead link
    assert (body["since_go_live"], body["recent_trades"], body["baseline_trades"]) == (2, 2, 1)
    habits = {h["key"]: h for h in body["habits"]}
    assert habits["expired_worthless"]["recent"] == {"n": 1, "trades": 2, "excluded": 0, "pct": 0.5, "pnl": -100.0}
    # NVDA peaked at +25% but only $25: not a green-to-red by the audit's $50 floor.
    assert habits["green_to_red"]["baseline"] == {"n": 0, "trades": 1, "excluded": 0, "pct": 0.0, "pnl": 0.0}
    assert habits["opened_green"]["baseline"] == {"n": 1, "trades": 1, "excluded": 0, "pct": 1.0, "pnl": -20.0}
    assert habits["held_hour_lost"]["baseline"]["n"] == 1
    assert body["responses"] == {"expired": 1, "closed_15m": 1, "unmatched": 1} and body["alerts_total"] == 3
    assert body["verdict"]["verdict"] == "not_enough_data"


def test_owner_only(boundary):  # noqa: F811
    assert boundary.owner.get("/analytics/exit-habits").status_code == 200
    assert boundary.public.get("/analytics/exit-habits").status_code == 401


def test_journal_readers_are_denied(boundary):  # noqa: F811
    from tests.test_browser_access import signin

    boundary.patch.setenv("TJ_ACCESS_SAMPLE_DATA", "true")
    created = boundary.owner.post("/access/assistants", json={"identifier": "reader",
        "grants": {"symbols": ["SPY"], "run_ids": [], "journal_read": True}})
    assert signin(boundary, identifier="reader", key=created.json()["key"]).status_code == 200
    assert boundary.public.get("/stats/analytics").status_code == 200  # the journal grant is real
    assert boundary.public.get("/analytics/exit-habits").status_code == 403


def test_a_rolled_close_is_not_read_as_a_sale_at_the_alert():
    out = follow_up(alert(), BUY + [{**f("sell_to_close", 2, 100.0, "2026-10-21T10:40"), "derived": True}], "closed")
    assert out["response"] == "rolled" and out["vs_alert"] is None and "rolled" in out["note"]
