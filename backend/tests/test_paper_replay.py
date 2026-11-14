"""Paper trading on a past day (``app/engine/paper_replay.py``): fills priced only from bars that ended by the replay
clock plus an assumed spread, options refused with the reason, limits and stop/target worked bar by bar with the live
book's rules (a bar touching both is the stop), everything sold at the replayed close, and replay runs kept apart from
the live paper run and real trades. Invented numbers, no network."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine as sa_create_engine, inspect, text
from sqlmodel import select

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import paper_book, paper_replay
from app.models import PaperEvent, PaperRun
from app.routers import copilot_paper
from tests.test_paper_book import db, key  # noqa: F401 -- fixtures
from tests.test_plan_target import _alembic

DAY = date(2026, 11, 13)
OPEN = int(datetime(2026, 11, 13, 14, 30, tzinfo=UTC).timestamp())  # 09:30 New York
CLOSE = int(datetime(2026, 11, 13, 21, 0, tzinfo=UTC).timestamp())  # 16:00 New York
NOW = datetime(2026, 11, 14, 17, 0, tzinfo=UTC).timestamp()  # Saturday: the replay is a past day
M = 60


def bar(minute, o, h, low, c):
    start = OPEN + minute * M
    return {"time": start, "end_time": start + M, "open": o, "high": h, "low": low, "close": c, "volume": 1000.0, "source": "alpaca_sip"}


# NBIS's replayed morning: the 09:30 bar closes 100, then a dip to 98.9, a run to 103 and a bar touching both 101 and 99.
BARS = [bar(-1, 99, 99.5, 98.5, 99.2),  # 09:29 premarket: on the chart, never a regular-session price
        bar(0, 99.5, 100.2, 99.4, 100.0), bar(1, 100.0, 100.3, 99.8, 100.1), bar(2, 100.1, 100.1, 98.9, 99.0),
        bar(3, 99.0, 101.0, 99.0, 100.9), bar(4, 100.9, 103.0, 100.8, 102.9), bar(5, 102.9, 103.0, 98.5, 99.5),
        bar(6, 99.6, 99.9, 99.2, 99.8), bar(389, 99.8, 99.9, 99.7, 99.85)]


@pytest.fixture(autouse=True)
def day(monkeypatch):
    state = SimpleNamespace(bars={"NBIS": list(BARS)}, reads=[])
    monkeypatch.setattr(paper_replay, "regular", lambda d: (OPEN, CLOSE) if d == DAY else None)

    def bars(symbol, d):
        state.reads.append((symbol, d))
        if symbol not in state.bars:
            raise paper_replay.ReplayError(f"No minute bars for {symbol} on Nov 13: history_unavailable", 409)
        return state.bars[symbol]
    monkeypatch.setattr(paper_replay, "bars", bars)
    paper_replay._kept.clear()
    return state


def at(minute):
    return OPEN + minute * M


def run(db, cash=None):  # noqa: F811
    return paper_replay.start(db, {"day": DAY.isoformat(), "starting_cash": cash}, NOW)


def buy(db, r, clock, qty=10, **extra):  # noqa: F811
    return paper_replay.order(db, {"run_id": str(r.id), "at": clock, "action": "open", "symbol": "NBIS", "instrument": "stock",
                                   "quantity": qty, "order_key": key(), **extra}, NOW)


def step(db, r, clock, end=False):  # noqa: F811
    return paper_replay.step(db, {"run_id": str(r.id), "at": clock, "end": end}, NOW)


def test_a_market_buy_fills_at_the_newest_completed_bar_plus_the_assumed_half_spread_never_a_later_bar(db):  # noqa: F811
    r = run(db)
    # 09:30:00: the first regular bar is still forming, and the premarket bar is no regular-session price.
    with pytest.raises(paper_replay.ReplayError, match="first minute is still forming"):
        buy(db, r, at(0))
    # 09:32:00: the 09:31 bar (close 100.10) is the newest completed; the 09:32 bar (low 98.90) is the future.
    preview = paper_replay.order(db, {"run_id": str(r.id), "at": at(2), "action": "open", "symbol": "NBIS", "instrument": "stock",
                                      "quantity": 10, "preview": True}, NOW)["preview"]
    assert (preview["close"], preview["half_spread"], preview["ask"], preview["bar"]) == (100.1, 0.03, 100.13, at(1))
    assert preview["per_share"] == -100.13 and preview["cash"] == -1001.3 and preview["buying_power_after"] == 8998.7
    assert db.exec(select(PaperEvent)).all() == []  # a preview stores nothing
    filled = buy(db, r, at(2), note="dip buy")
    assert filled["filled"]["cash"] == -1001.3 and filled["filled"]["at"] == at(2) - 1
    [held] = filled["positions"]
    assert held["note"] == "dip buy" and held["stock"] == 100.1
    assert held["mark"]["per_share"] == 100.1 and held["mark"]["pnl"] == -0.3  # marked at the clock's bar, no spread
    assert filled["account"]["cash"] == 8998.7
    # Selling at 09:35 takes the 09:34 bar's close 102.90 less 0.03.
    sold = paper_replay.order(db, {"run_id": str(r.id), "at": at(5), "action": "close", "position_id": held["id"], "order_key": key()}, NOW)
    assert sold["filled"]["per_share"] == 102.87 and sold["filled"]["pnl"] == 27.4  # 1028.70 − 1001.30
    [trade] = sold["closed"]
    assert trade["realized"] == 27.4 and trade["day"] == "2026-11-13" and trade["note"] == "dip buy"


def test_a_stale_bar_options_and_the_clock_going_back_are_refused(db, day):  # noqa: F811
    r = run(db)
    with pytest.raises(paper_replay.ReplayError, match="no fill on a stale price"):
        buy(db, r, at(100))  # the newest bar ended at 09:37, far more than two minutes before
    with pytest.raises(paper_replay.ReplayError, match="Options are not replayed yet"):
        paper_replay.order(db, {"run_id": str(r.id), "at": at(3), "action": "open", "symbol": "NBIS", "instrument": "option",
                                "option_type": "call", "expiry": "2026-11-20", "strike": 100, "quantity": 1, "order_key": key()}, NOW)
    buy(db, r, at(4))
    with pytest.raises(paper_replay.ReplayError, match="only goes forward"):
        buy(db, r, at(2))
    with pytest.raises(paper_replay.ReplayError, match="outside the replayed day"):
        step(db, r, CLOSE + M)
    with pytest.raises(paper_replay.ReplayError, match="today's session is live paper"):
        paper_replay.start(db, {"day": "2026-11-14"}, NOW)


def test_a_buy_limit_works_bar_by_bar_and_fills_at_the_limit_or_the_better_open(db):  # noqa: F811
    r = run(db)
    placed = buy(db, r, at(2), order_type="limit", limit_price=99.10, stop=98.0, target=102.5)
    assert placed["filled"] is None and placed["working"]["limit"] == 99.1 and placed["working"]["expires_at"] == CLOSE
    assert placed["account"]["reserved"] == 991.0 and placed["account"]["buying_power"] == 9009.0
    # The 09:32 bar (low 98.90 + 0.03 ≤ 99.10) fills at the limit: its open 100.10 + 0.03 is above it.
    stepped = step(db, r, at(3))
    [filled] = stepped["happened"]
    assert (filled["kind"], filled["price"], filled["at"]) == ("limit", 99.1, at(2) + 59)
    [held] = stepped["positions"]
    assert held["per_share"] == -99.1 and stepped["account"]["cash"] == 9009.0 and stepped["orders"] == []
    # Switch off: the 09:34 bar's high 103 touches the target; it is only recorded.
    stepped = step(db, r, at(5))
    assert [h["kind"] for h in stepped["happened"]] == ["touch"] and stepped["positions"][0]["touched"]["target"] == at(5)
    assert stepped["positions"][0]["status"] == "open"


def test_close_automatically_a_bar_touching_both_is_the_stop_and_it_sells_at_the_next_open(db):  # noqa: F811
    r = run(db)
    buy(db, r, at(5), stop=99.0, target=103.5, auto=True)  # at the 09:34 bar's close 102.90 + 0.03
    # The 09:35 bar reaches 103.0 and 98.5: only the stop (99) is touched; the exit sells at the 09:36 open 99.60 − 0.03.
    stepped = step(db, r, at(7))
    assert [(h["kind"], h["price"]) for h in stepped["happened"]] == [("stop", 99.57)]
    [trade] = stepped["closed"]
    assert trade["verdict"]["kind"] == "stop" and trade["verdict"]["auto"] is True
    assert trade["realized"] == round((99.57 - 102.93) * 10, 2) == -33.6


def test_a_bar_touching_both_levels_counts_as_the_stop(db, day):  # noqa: F811
    day.bars["NBIS"] = [bar(0, 100, 100, 100, 100), bar(1, 100, 101.5, 98.5, 100), bar(2, 100.4, 100.5, 100.3, 100.4)]
    r = run(db)
    buy(db, r, at(1), stop=99.0, target=101.0, auto=True)
    [exit_] = step(db, r, at(3))["happened"]
    assert exit_["kind"] == "stop" and exit_["price"] == 100.37


def test_at_the_close_orders_lapse_and_positions_sell_at_the_last_close_apart_from_live_paper(db):  # noqa: F811
    paper_book.start_run(db, None, False, NOW - 10_000)  # his live paper account
    r = run(db, cash=5000)
    buy(db, r, at(5), qty=10, note="breakout")
    buy(db, r, at(6), qty=5, order_type="limit", limit_price=90.0)
    ended = step(db, r, CLOSE)
    assert ended["ended"] and ended["orders"] == [] and ended["positions"] == []
    [trade] = ended["closed"]
    assert trade["verdict"]["kind"] == "flat" and trade["exits"][0]["per_share"] == 99.82  # 15:59 close 99.85 − 0.03
    # Live paper never sees the replay run; the replay scorecard holds it with its day and note.
    assert paper_book.current_run(db).kind == "live"
    live = paper_book.view(db, NOW)
    assert live["run"]["number"] == 1 and live["earlier"] == [] and live["closed"] == []
    card = paper_replay.scorecard(db)
    assert card["score"]["trades"] == 1 and card["score"]["pnl"] == trade["realized"]
    assert card["trades"][0]["note"] == "breakout" and card["runs"][0]["day"] == "2026-11-13" and card["runs"][0]["starting_cash"] == 5000


def test_leaving_early_sells_at_the_clock(db):  # noqa: F811
    r = run(db)
    buy(db, r, at(3))
    left = step(db, r, at(5), end=True)
    [trade] = left["closed"]
    assert trade["verdict"]["kind"] == "left" and trade["exits"][0]["per_share"] == 102.87


def test_the_routes_are_owner_only_and_a_day_without_bars_says_why(db, day, monkeypatch):  # noqa: F811
    for route in ("GET /copilot/paper/replay", "GET /copilot/paper/replay/day", "GET /copilot/paper/replay/bars",
                  "POST /copilot/paper/replay/runs", "POST /copilot/paper/replay/step", "POST /copilot/paper/replay/orders",
                  "POST /copilot/paper/replay/orders/cancel", "POST /copilot/paper/replay/auto"):
        assert route in DOMAIN_ROUTES
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    monkeypatch.setattr(paper_replay, "days", lambda now: [{"date": "2026-11-13", "open_at": OPEN, "close_at": CLOSE, "early_close": False}])
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        assert "days" not in client.get("/copilot/paper/replay").json()
        home = client.get("/copilot/paper/replay", params={"with_days": "true"}).json()
        assert home["days"][0]["date"] == "2026-11-13" and home["score"]["trades"] == 0 and "Shares only" in home["options"]
        missing = client.get("/copilot/paper/replay/bars", params={"day": "2026-11-13", "symbol": "ZZZZ"})
        assert missing.status_code == 409 and "No minute bars for ZZZZ" in missing.json()["detail"]
        got = client.get("/copilot/paper/replay/bars", params={"day": "2026-11-13", "symbol": "nbis"}).json()
        assert got["open_at"] == OPEN and len(got["bars"]) == len(BARS) and set(got["bars"][0]) == {"time", "open", "high", "low", "close", "volume"}
        started = client.post("/copilot/paper/replay/runs", json={"day": "2026-11-13"}).json()
        assert started["at"] == OPEN and started["account"]["cash"] == 10000
        rid = started["run"]["id"]
        filled = client.post("/copilot/paper/replay/orders", json={"run_id": rid, "at": at(3), "action": "open", "symbol": "NBIS",
                                                                   "instrument": "stock", "quantity": 1, "order_key": key(),
                                                                   "stop": 98, "target": 104})
        assert filled.status_code == 200, filled.text  # simulated evidence: replay never needs a live quote
        pid = filled.json()["positions"][0]["id"]
        on = client.post("/copilot/paper/replay/auto", json={"run_id": rid, "at": at(3), "position_id": pid, "on": True, "order_key": key()})
        assert on.json()["positions"][0]["auto"] is True
        placed = client.post("/copilot/paper/replay/orders", json={"run_id": rid, "at": at(3), "action": "close", "position_id": pid,
                                                                   "order_type": "limit", "limit_price": 110, "order_key": key()}).json()
        canceled = client.post("/copilot/paper/replay/orders/cancel", json={"run_id": rid, "at": at(4), "order_id": placed["working"]["id"]})
        assert canceled.json()["orders"] == []
        assert client.post("/copilot/paper/replay/step", json={"run_id": rid, "at": CLOSE}).json()["ended"]
        assert db.exec(select(PaperRun).where(PaperRun.kind == "replay")).one().replay_day == DAY


def test_replay_never_reaches_robinhood_tradier_or_the_real_books():
    text_ = (Path(__file__).resolve().parents[1] / "app/engine/paper_replay.py").read_text()
    for word in ("robinhood", "_live_quotes", "chart_feed", "tradier", "Trade,", "Fill,", "shadow_book"):
        assert word not in text_


def test_the_migration_adds_the_run_kind_and_keeps_existing_runs_live(tmp_path):
    path = tmp_path / "paper.sqlite"
    _alembic(path, "upgrade", "a7c3e9f1b5d2")
    engine = sa_create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO paper_run (id, starting_cash, started_at) VALUES ('00000000000000000000000000000001', 10000, '2026-11-13 15:00:00')"))
    before = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in inspect(engine).get_table_names()}
    engine.dispose()
    _alembic(path, "upgrade", "7f3b276ac082")
    engine = sa_create_engine(f"sqlite:///{path}")
    after = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in inspect(engine).get_table_names()}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT kind, replay_day FROM paper_run")).all() == [("live", None)]
    engine.dispose()
    assert after["paper_run"] == before["paper_run"] + ["kind", "replay_day"]
    assert {k: v for k, v in after.items() if k != "paper_run"} == {k: v for k, v in before.items() if k != "paper_run"}
    _alembic(path, "downgrade", "a7c3e9f1b5d2")
