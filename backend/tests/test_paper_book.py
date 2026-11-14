"""His own paper book (``app/engine/paper_book.py``): fills at the ask to buy and the bid to sell on a fresh quote only,
cash and buying power with the ×100 option multiplier, credit-spread collateral, trims and closes whose realized P&L adds
up to the cent, expiry settled at intrinsic value from the close, the scorecard beside his real trades, and the
additive migration. It never writes fills, trades or accounts and never reaches Robinhood. No network."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine as sa_create_engine, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import desk_minute, paper_book
from app.models import Account, Fill, PaperEvent, PaperRun, Trade
from app.routers import copilot_paper
from tests.test_plan_target import _alembic

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC).timestamp()  # Friday 10:00 New York
CLOSE = datetime(2026, 11, 13, 21, 0, tzinfo=UTC).timestamp()  # 16:00 New York
CALL = "NBIS261120C00100000"
P95, P90 = "NBIS261120P00095000", "NBIS261120P00090000"
ROTH, WEBULL = UUID(int=1), UUID(int=3)


def q(symbol, bid, ask, age=5.0, last=None, now=NOW):
    stamp = int((now - age) * 1000)
    return SimpleNamespace(symbol=symbol, bid=bid, ask=ask, bid_date=stamp, ask_date=stamp, last=last, mid=None)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267"))
        session.add(Account(id=WEBULL, name="Webull", type="individual", last4="9999", broker="webull"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def market(monkeypatch):
    """An open market whose quotes the test sets, the desk's kept marks, and the closes the test names."""
    state = SimpleNamespace(open=True, quotes={}, marks={}, closes={}, reads=[])
    monkeypatch.setattr(paper_book, "_market_open", lambda now: state.open)

    def quotes(symbols):
        state.reads.append(sorted(symbols))
        return {s: state.quotes[s] for s in symbols if s in state.quotes}
    monkeypatch.setattr(paper_book, "_live_quotes", quotes)
    monkeypatch.setattr(paper_book, "_marks", lambda symbols: {s: state.marks[s] for s in symbols if s in state.marks})
    monkeypatch.setattr(paper_book, "_close_for", lambda symbol, day, now: state.closes.get((symbol, day)))
    monkeypatch.setattr(paper_book, "_close_moment", lambda day: datetime(day.year, day.month, day.day, 21, tzinfo=UTC).timestamp())
    return state


def key():
    return uuid4().hex


def buy_call(db, qty=2, now=NOW, **extra):
    return paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                      "strike": 100, "quantity": qty, "order_key": key(), **extra}, now)


def test_a_run_starts_at_ten_thousand_and_a_reset_keeps_the_old_runs_history(db, market):
    assert paper_book.view(db, NOW)["run"] is None
    paper_book.start_run(db, None, False, NOW)
    with pytest.raises(paper_book.PaperError) as refused:
        paper_book.start_run(db, 5000, False, NOW + 1)
    assert refused.value.status == 409
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    buy_call(db)
    paper_book.start_run(db, 2500, True, NOW + 60)
    shown = paper_book.view(db, NOW + 61)
    assert shown["run"]["number"] == 2 and shown["run"]["starting_cash"] == 2500
    assert shown["account"]["cash"] == 2500 and shown["positions"] == []
    [first] = shown["earlier"]
    assert first["number"] == 1 and first["starting_cash"] == 10000 and first["left_open"] == 1
    assert len(db.exec(select(PaperRun)).all()) == 2 and len(db.exec(select(PaperEvent)).all()) == 1
    with pytest.raises(paper_book.PaperError):
        paper_book.start_run(db, 50, True, NOW + 70)  # below the smallest start


def test_a_call_fills_at_the_ask_times_one_hundred_and_closes_at_the_bid(db, market):
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    preview = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                         "strike": 100, "quantity": 2}, NOW, preview=True)["preview"]
    assert preview["per_share"] == -3.40 and preview["cash"] == -680.00 and preview["buying_power_after"] == 9320.00
    assert preview["buying_power"] == 10000.00 and preview["need_each"] == 340.0
    assert db.exec(select(PaperEvent)).all() == []  # a preview stores nothing
    filled = buy_call(db, note="  reclaim of 98\n on volume ", stop=95, target=105)["filled"]
    assert filled["cash"] == -680.00 and filled["label"] == "NBIS $100 Call 11/20/26"
    book = paper_book.view(db, NOW + 30)
    assert book["account"] == {"cash": 9320.0, "collateral": 0.0, "buying_power": 9320.0, "equity": None, "pnl": None, "unpriced": 1, "prices_at": None}
    [held] = book["positions"]
    assert held["note"] == "reclaim of 98 on volume" and held["mark"] is None  # no price yet: never a zero
    # The desk's ticked mark moves the live P&L: 4.00 × 100 × 2 − 680 = +120.
    market.marks = {CALL: {"last": 4.00, "at": int(NOW + 20)}}
    book = paper_book.view(db, NOW + 30)
    assert book["positions"][0]["mark"] == {"per_share": 4.0, "value": 800.0, "pnl": 120.0, "pct": 17.6, "at": int(NOW + 20)}
    assert book["account"]["equity"] == 10120.0 and book["account"]["pnl"] == 120.0
    # Trim one at the bid 3.90, then close the other at the bid 2.90: +50 then −50; the cash adds up to the cent.
    market.quotes = {CALL: q(CALL, 3.90, 4.10, now=NOW + 600), "NBIS": q("NBIS", 101, 101.1, last=101.05, now=NOW + 600)}
    trim = paper_book.close_order(db, {"position_id": filled["position_id"], "quantity": 1, "order_key": key()}, NOW + 600)["filled"]
    assert trim["cash"] == 390.0 and trim["pnl"] == 50.0 and not trim["all"]
    market.quotes = {CALL: q(CALL, 2.90, 3.00, now=NOW + 900), "NBIS": q("NBIS", 96, 96.1, last=96.0, now=NOW + 900)}
    out = paper_book.close_order(db, {"position_id": filled["position_id"], "order_key": key()}, NOW + 900)["filled"]
    assert out["cash"] == 290.0 and out["pnl"] == -50.0 and out["all"]
    book = paper_book.view(db, NOW + 1000)
    assert book["account"]["cash"] == 10000.0 and book["positions"] == []
    [closed] = book["closed"]
    assert closed["realized"] == 0.0 and closed["status"] == "closed"
    assert closed["verdict"]["kind"] == "early"  # 96 is above the 95 stop and below the 105 target
    assert book["score"]["paper"]["pnl"] == 0.0 and book["score"]["paper"]["trades"] == 1
    with pytest.raises(paper_book.PaperError):
        paper_book.close_order(db, {"position_id": filled["position_id"], "order_key": key()}, NOW + 1100)


def test_a_stale_quote_a_closed_market_or_no_quote_refuses_with_the_quotes_time(db, market):
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40, age=600), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    with pytest.raises(paper_book.PaperError) as stale:
        buy_call(db)
    assert stale.value.status == 409 and "Nov 13 9:50 AM ET, not live" in str(stale.value)
    one_side = q(CALL, 3.30, 3.40)
    one_side.bid_date = int((NOW - 900) * 1000)  # the ask moved, the bid did not: both sides must be fresh
    market.quotes[CALL] = one_side
    with pytest.raises(paper_book.PaperError, match="not live"):
        buy_call(db)
    market.quotes[CALL] = q(CALL, None, 3.40)
    with pytest.raises(paper_book.PaperError, match="no usable bid and ask"):
        buy_call(db)
    del market.quotes[CALL]
    with pytest.raises(paper_book.PaperError, match="No quote"):
        buy_call(db)
    market.open = False
    market.quotes[CALL] = q(CALL, 3.30, 3.40)
    with pytest.raises(paper_book.PaperError, match="market is closed"):
        buy_call(db)
    assert db.exec(select(PaperEvent)).all() == []


def test_an_order_he_cannot_afford_is_refused(db, market):
    paper_book.start_run(db, 1000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    with pytest.raises(paper_book.PaperError) as refused:
        buy_call(db, qty=3)  # 3 × 3.40 × 100 = $1,020
    assert "needs $1,020.00 and you have $1,000.00" in str(refused.value)
    assert buy_call(db, qty=2)["filled"]["cash"] == -680.0


def test_shares_buy_at_the_ask_and_sell_at_the_bid_with_no_multiplier(db, market):
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {"AAPL": q("AAPL", 100.00, 100.05, last=100.02)}
    filled = paper_book.open_order(db, {"symbol": "aapl", "instrument": "stock", "quantity": 10, "order_key": key(),
                                        "stop": 98, "target": 104}, NOW)["filled"]
    assert filled["cash"] == -1000.50 and filled["label"] == "AAPL shares"
    market.quotes = {"AAPL": q("AAPL", 104.10, 104.15, last=104.12, now=NOW + 60)}
    out = paper_book.close_order(db, {"position_id": filled["position_id"], "order_key": key()}, NOW + 60)["filled"]
    assert out["cash"] == 1041.00 and out["pnl"] == 40.50
    [closed] = paper_book.view(db, NOW + 61)["closed"]
    assert closed["verdict"] == {"kind": "target", "text": "Took the target: stock 104.12 vs target 104"}


def test_a_stop_or_target_on_the_wrong_side_of_the_stock_is_refused(db, market):
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {"AAPL": q("AAPL", 100.00, 100.05, last=100.02)}
    with pytest.raises(paper_book.PaperError, match="stop is a stock price below 100.02"):
        paper_book.open_order(db, {"symbol": "AAPL", "instrument": "stock", "quantity": 1, "order_key": key(), "stop": 101}, NOW)
    market.quotes = {"NBIS261120P00095000": q(P95, 2.0, 2.1), "NBIS": q("NBIS", 98, 98.1, last=98.05)}
    with pytest.raises(paper_book.PaperError, match="target is a stock price below 98.05"):  # a put gains as it falls
        paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "put", "expiry": "2026-11-20",
                                   "strike": 95, "quantity": 1, "order_key": key(), "target": 99}, NOW)


def test_a_credit_spread_holds_its_width_and_settles_at_intrinsic_value_after_the_close(db, market):
    paper_book.start_run(db, None, False, NOW)
    P95, P90 = "NBIS261113P00095000", "NBIS261113P00090000"  # noqa: N806 -- this week's contracts
    market.quotes = {P95: q(P95, 2.00, 2.10), P90: q(P90, 0.70, 0.80), "NBIS": q("NBIS", 98, 98.1, last=98.05)}
    spread = {"symbol": "NBIS", "instrument": "spread", "option_type": "put", "expiry": "2026-11-13", "long_strike": 90,
              "short_strike": 95, "quantity": 1, "stop": 94, "target": 100}
    filled = paper_book.open_order(db, {**spread, "order_key": key()}, NOW)["filled"]
    assert filled["per_share"] == 1.20 and filled["cash"] == 120.0  # the 95 put sold at its bid, the 90 bought at its ask
    assert filled["label"] == "NBIS $90/$95 Put Credit Spread 11/13/26"
    book = paper_book.view(db, NOW + 1)
    assert book["account"] | {} == {**book["account"], "cash": 10120.0, "collateral": 500.0, "buying_power": 9620.0}
    # The legs' marks: the spread is worth −(1.50 − 0.40) = −1.10 a share: −110 against the 120 taken in, +10.
    market.marks = {P95: {"last": 1.50, "at": int(NOW)}, P90: {"last": 0.40, "at": int(NOW)}}
    assert paper_book.view(db, NOW + 2)["positions"][0]["mark"]["pnl"] == 10.0
    # Before the settle time it stays open; after it with no close it waits; with the 93 close it settles.
    assert paper_book.view(db, CLOSE + 60)["positions"][0]["status"] == "open"
    waiting = paper_book.view(db, CLOSE + 1000)["positions"][0]
    assert waiting["status"] == "open" and waiting["awaiting_close"]
    market.closes[("NBIS", date(2026, 11, 13))] = 93.0
    book = paper_book.view(db, CLOSE + 1000)
    [closed] = book["closed"]
    # 90 put worth 0, 95 put worth 2.00 against him: −200; with the 120 credit, −80.
    assert closed["status"] == "expired" and closed["realized"] == -80.0
    assert closed["exits"][0]["cash"] == -200.0 and closed["verdict"]["kind"] == "expiry"
    assert book["account"]["cash"] == 9920.0 and book["account"]["collateral"] == 0.0
    paper_book.view(db, CLOSE + 2000)  # a second read never settles twice
    assert len(db.exec(select(PaperEvent).where(PaperEvent.kind == "expire")).all()) == 1


def test_a_debit_spread_pays_the_natural_price_and_a_long_call_expires_worthless(db, market):
    paper_book.start_run(db, None, False, NOW)
    c105 = "NBIS261113C00105000"
    c100 = "NBIS261113C00100000"
    market.quotes = {c100: q(c100, 1.90, 2.00), c105: q(c105, 0.50, 0.55), "NBIS": q("NBIS", 98, 98.1, last=98.05)}
    debit = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "spread", "option_type": "call", "expiry": "2026-11-13",
                                       "long_strike": 100, "short_strike": 105, "quantity": 2, "order_key": key()}, NOW)["filled"]
    assert debit["per_share"] == -1.50 and debit["cash"] == -300.0
    single = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-13",
                                        "strike": 105, "quantity": 1, "order_key": key()}, NOW)["filled"]
    assert single["cash"] == -55.0
    market.closes[("NBIS", date(2026, 11, 13))] = 102.0
    book = paper_book.view(db, CLOSE + 1000)
    by = {c["label"]: c for c in book["closed"]}
    assert by["NBIS $105 Call 11/13/26"]["realized"] == -55.0  # worthless: the premium is the loss
    assert by["NBIS $100/$105 Call Debit Spread 11/13/26"]["realized"] == 100.0  # 2.00 × 100 × 2 − 300
    score = book["score"]["paper"]
    assert score == {**score, "trades": 2, "pnl": 45.0, "win_rate": 50.0, "avg_win": 100.0, "avg_loss": -55.0, "largest_loss": -55.0}
    assert score["curve"] == [{"day": "2026-11-13", "pnl": 45.0}]


def test_a_double_tap_records_one_fill(db, market):
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    order = {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20", "strike": 100,
             "quantity": 1, "order_key": "tap-0123456789"}
    assert paper_book.open_order(db, order, NOW)["filled"]
    assert paper_book.open_order(db, order, NOW + 1) == {"filled": None, "duplicate": True}
    assert len(db.exec(select(PaperEvent)).all()) == 1


def test_his_real_closed_trades_over_the_same_dates_sit_beside_paper_and_are_never_written(db, market):
    paper_book.start_run(db, None, False, NOW)

    def trade(pnl, closed, account=ROTH):
        db.add(Trade(account_id=account, ticker="NVDA", instrument_type="option", contracts=1, avg_entry_premium=1,
                     total_premium_paid=100, realized_pnl=pnl, opened_at=closed, closed_at=closed, status="closed"))
    trade(200, datetime(2026, 11, 13, 11, 0))  # New York times, after the 10:00 start
    trade(-150, datetime(2026, 11, 14, 10, 0))
    trade(999, datetime(2026, 11, 13, 9, 45))  # before the run started
    trade(777, datetime(2026, 11, 13, 12, 0), account=WEBULL)  # Webull stays out
    db.commit()
    before = [(t.id, t.realized_pnl, t.status) for t in db.exec(select(Trade)).all()]
    real = paper_book.view(db, NOW + 100)["score"]["real"]
    assert real == {**real, "trades": 2, "pnl": 50.0, "win_rate": 50.0, "avg_win": 200.0, "avg_loss": -150.0, "largest_loss": -150.0}
    assert real["curve"] == [{"day": "2026-11-13", "pnl": 200.0}, {"day": "2026-11-14", "pnl": 50.0}]
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    buy_call(db)
    assert [(t.id, t.realized_pnl, t.status) for t in db.exec(select(Trade)).all()] == before
    assert db.exec(select(Fill)).all() == []


def test_the_routes_are_owner_only_batched_and_refuse_simulated_evidence(db, market, monkeypatch):
    for route in ("GET /copilot/paper", "POST /copilot/paper/runs", "POST /copilot/paper/orders"):
        assert route in DOMAIN_ROUTES
    assert desk_minute.allowed("/copilot/paper")
    frontend = (Path(__file__).resolve().parents[2] / "frontend/lib/deskMinute.ts").read_text()
    assert '"/copilot/paper"' in frontend
    evidence = {"value": "live"}
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence=evidence["value"]))
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        assert client.get("/copilot/paper").json()["run"] is None
        started = client.post("/copilot/paper/runs", json={})
        assert started.status_code == 200 and started.json()["account"]["cash"] == 10000
        assert client.post("/copilot/paper/runs", json={"starting_cash": 5000}).status_code == 409
        market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
        order = {"action": "open", "symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                 "strike": 100, "quantity": 1}
        assert client.post("/copilot/paper/orders", json={**order, "preview": True}).json()["preview"]["cash"] == -340.0
        filled = client.post("/copilot/paper/orders", json={**order, "order_key": key()})
        assert filled.status_code == 200 and filled.json()["filled"]["cash"] == -340.0
        market.open = False
        closed = client.post("/copilot/paper/orders", json={"action": "close", "position_id": filled.json()["filled"]["position_id"], "order_key": key()})
        assert closed.status_code == 409 and "market is closed" in closed.json()["detail"]
        evidence["value"] = "fixture"
        assert client.post("/copilot/paper/orders", json={**order, "order_key": key()}).status_code == 409


def test_paper_never_reaches_robinhood_or_the_real_books():
    for path in ("app/engine/paper_book.py", "app/routers/copilot_paper.py"):
        text = (Path(__file__).resolve().parents[1] / path).read_text()
        assert "robinhood_read" not in text and "import robinhood" not in text
        assert "shadow_book" not in text and "Fill" not in text.replace("Fills", "")


def test_the_migration_adds_only_the_two_paper_tables(tmp_path):
    path = tmp_path / "paper.sqlite"
    _alembic(path, "upgrade", "e2c6a8f4b1d9")
    engine = sa_create_engine(f"sqlite:///{path}")
    before = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in inspect(engine).get_table_names()}
    engine.dispose()
    _alembic(path, "upgrade", "a7c3e9f1b5d2")
    engine = sa_create_engine(f"sqlite:///{path}")
    after = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in inspect(engine).get_table_names()}
    engine.dispose()
    assert set(after) - set(before) == {"paper_run", "paper_event"}
    assert {k: v for k, v in after.items() if k in before} == before
    _alembic(path, "downgrade", "e2c6a8f4b1d9")


def test_two_closes_racing_never_make_cash_and_a_trim_waits_for_the_rest_in_closed_pnl(db, market):
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    filled = buy_call(db, qty=2)["filled"]
    market.quotes = {CALL: q(CALL, 3.40, 3.50, now=NOW + 60), "NBIS": q("NBIS", 99, 99.1, last=99.05, now=NOW + 60)}
    paper_book.close_order(db, {"position_id": filled["position_id"], "quantity": 1, "order_key": key()}, NOW + 60)  # trim +$0
    market.quotes = {CALL: q(CALL, 3.90, 4.00, now=NOW + 120), "NBIS": q("NBIS", 101, 101.1, last=101.05, now=NOW + 120)}
    book = paper_book.view(db, NOW + 61)
    assert book["score"]["paper"] == {**book["score"]["paper"], "trades": 0, "pnl": 0.0, "curve": []}  # a trim is not a closed trade
    # Two closes of the last contract read the book before either was stored (phone and desk): the second is stored
    # but counts for nothing; cash moves once.
    run = paper_book.current_run(db)
    data = {"quantity": 1, "per_share": 3.9, "cash": 390.0, "legs_filled": {}, "stock": 101.05}
    for n in range(2):
        paper_book._store(db, run, UUID(filled["position_id"]), "close", f"race-close-{n}", NOW + 120, data)
    book = paper_book.view(db, NOW + 130)
    assert book["account"]["cash"] == 10000.0 - 680.0 + 340.0 + 390.0
    [closed] = book["closed"]
    assert closed["realized"] == 50.0 and book["score"]["paper"]["pnl"] == 50.0
    # An over-sized close counts only the share that was left, its cash scaled to it.
    market.quotes = {CALL: q(CALL, 3.30, 3.40, now=NOW + 200), "NBIS": q("NBIS", 98.0, 98.1, last=98.05, now=NOW + 200)}
    other = buy_call(db, qty=1, now=NOW + 200)["filled"]
    paper_book._store(db, run, UUID(other["position_id"]), "close", "too-many", NOW + 260, {**data, "quantity": 3, "cash": 1170.0})
    book = paper_book.view(db, NOW + 270)
    assert book["account"]["cash"] == 10050.0 - 340.0 + 390.0
