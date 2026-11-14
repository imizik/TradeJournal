"""Redo a real trade in replay (``app/engine/replay_redo.py``): the plan names the day, ticker and contract and nothing
about how the trade went; a redo is a replay run linked to the trade; the comparison puts both sides and the difference
side by side with one line built from the facts; Redo my worst lists the biggest real losses Replay can play. The real
trade is only ever read. Invented numbers, no network."""

from datetime import date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import select

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import day_journal, paper_replay, replay_redo
from app.models import Fill, PaperEvent, Trade
from app.routers import copilot_paper
from tests.test_paper_book import ROTH, WEBULL, db, key  # noqa: F401 -- fixtures
from tests.test_paper_replay import CLOSE, DAY, NOW, OPEN, at, buy, day, step  # noqa: F401 -- fixtures and helpers

DAYS = [{"date": "2026-11-13", "open_at": OPEN, "close_at": CLOSE, "early_close": False},
        {"date": "2026-11-12", "open_at": OPEN - 86400, "close_at": CLOSE - 86400, "early_close": False}]


@pytest.fixture(autouse=True)
def window(monkeypatch):
    """Options replayable on the replayed day unless a test says otherwise; nothing hidden."""
    state = SimpleNamespace(off=None, hidden=set())
    monkeypatch.setattr(replay_redo.ro, "off_reason", lambda d, now: state.off)
    monkeypatch.setattr(day_journal, "quiet", lambda session: state.hidden)
    return state


def trade(db, ticker="NBIS", pnl=-10.0, opened=datetime(2026, 11, 13, 9, 33), closed=datetime(2026, 11, 13, 9, 40),  # noqa: F811
          qty=10, entry=100.0, exit_=99.0, account=ROTH, status="closed", option=False):
    row = Trade(account_id=account, ticker=ticker, instrument_type="option" if option else "stock", contracts=qty,
                option_type="call" if option else None, strike=100 if option else None,
                expiration=date(2026, 11, 20) if option else None, avg_entry_premium=entry,
                avg_exit_premium=None if status == "open" else exit_, total_premium_paid=entry * qty * (100 if option else 1),
                realized_pnl=None if status == "open" else pnl, opened_at=opened, closed_at=None if status == "open" else closed,
                status=status, hold_duration_mins=None if status == "open" else int((closed - opened).total_seconds() // 60))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_the_plan_names_the_day_ticker_and_contract_and_nothing_about_how_it_went(db, window):  # noqa: F811
    call = trade(db, option=True, entry=2.5, exit_=1.5, pnl=-200.0, qty=2)
    plan = replay_redo.plan(db, str(call.id), NOW)
    assert (plan["day"], plan["symbol"], plan["instrument"]) == ("2026-11-13", "NBIS", "option")
    assert plan["contract"] == {"option_type": "call", "expiry": "2026-11-20", "strike": 100.0, "label": "NBIS $100 Call 11/20/26"}
    assert plan["shares_reason"] is None and plan["open_at"] == OPEN
    # 15 minutes before the 09:33 entry is premarket: the redo starts at the open, and says why.
    assert plan["before_at"] is None and "within 15 minutes of the open" in plan["before_reason"]


def test_the_plan_starts_15_minutes_before_the_entry_and_falls_back_to_shares_outside_the_option_window(db, window):  # noqa: F811
    early = trade(db, option=True, opened=datetime(2026, 11, 13, 9, 33))
    assert replay_redo.plan(db, str(early.id), NOW)["before_at"] is None  # within 15 minutes of the open
    late = trade(db, option=True, opened=datetime(2026, 11, 13, 11, 7, 30))
    plan = replay_redo.plan(db, str(late.id), NOW)
    assert plan["before_at"] == OPEN + 82 * 60  # 10:52, on the minute
    assert not {"pnl", "entry", "exit", "fills", "note", "realized_pnl"} & set(plan)
    window.off = "Option replay needs each contract's own minute trades ... Shares only on this day."
    plan = replay_redo.plan(db, str(late.id), NOW)
    assert plan["contract"] is None and plan["shares_reason"] == window.off
    with pytest.raises(paper_replay.ReplayError, match="still open"):
        replay_redo.plan(db, str(trade(db, status="open").id), NOW)
    today = trade(db, opened=datetime(2026, 11, 14, 10, 0), closed=datetime(2026, 11, 14, 10, 5))
    with pytest.raises(paper_replay.ReplayError, match="today's session is live paper"):
        replay_redo.plan(db, str(today.id), datetime(2026, 11, 14, 17, 0).timestamp())
    with pytest.raises(paper_replay.ReplayError, match="not in the journal"):
        replay_redo.plan(db, str(uuid4()), NOW)


def test_a_redo_is_a_linked_replay_run_and_the_comparison_puts_both_sides_side_by_side(db):  # noqa: F811
    real = trade(db)  # 10 NBIS 09:33 → 09:40, 100.00 → 99.00, −$10
    before = (real.status, float(real.realized_pnl), real.closed_at)
    started = replay_redo.start(db, {"trade_id": str(real.id), "start": "open"}, NOW)
    run_id = started["run"]["id"]
    assert started["run"]["redo_of"] == str(real.id) and started["redo"]["start_at"] == OPEN and started["at"] == OPEN
    r = paper_replay._run(db, run_id)
    buy(db, r, at(2), qty=5)  # 09:31 bar close 100.10 + 0.03
    [held] = paper_replay.view(db, r, at(2))["positions"]
    sold = paper_replay.order(db, {"run_id": run_id, "at": at(5), "action": "close", "position_id": held["id"], "order_key": key()}, NOW)
    [closed] = sold["closed"]
    assert closed["source"] == "redo" and closed["redo_of"] == str(real.id)  # tagged for "redos vs originals"
    out = replay_redo.compare(db, run_id)
    assert out["real"]["entry"] == {"price": 100.0, "at": datetime(2026, 11, 13, 9, 33, tzinfo=replay_redo.ET).timestamp()}
    assert out["real"]["exit"]["price"] == 99.0 and out["real"]["pnl"] == -10.0 and out["real"]["held_minutes"] == 7
    redo = out["redo"]
    assert redo["quantity"] == 5 and redo["entry"]["price"] == 100.13 and redo["exit"]["price"] == 102.87
    assert redo["entry"]["at"] == at(2) - 1 and redo["exit"]["at"] == at(5) - 1 and redo["held_minutes"] == 3
    assert redo["pnl"] == 13.7  # 5 × (102.87 − 100.13)
    assert out["difference"] == 23.7  # redo less real: 13.70 − (−10.00)
    assert out["note"] == "Exited 5 min earlier, smaller size (5 vs 10 shares)."
    # The real trade is only read: unchanged, and no fill was written.
    db.refresh(real)
    assert (real.status, float(real.realized_pnl), real.closed_at) == before and db.exec(select(Fill)).all() == []
    assert paper_replay.scorecard(db)["trades"][0]["redo_of"] == str(real.id)


def test_skipping_it_counts_as_zero_and_a_plain_replay_is_not_a_redo(db):  # noqa: F811
    real = trade(db, pnl=-400.0)
    run_id = replay_redo.start(db, {"trade_id": str(real.id)}, NOW)["run"]["id"]
    step(db, paper_replay._run(db, run_id), CLOSE)
    out = replay_redo.compare(db, run_id)
    assert out["redo"] is None and out["difference"] == 400.0 and out["note"] == "You skipped it: no trade in the redo."
    plain = paper_replay.start(db, {"day": DAY.isoformat()}, NOW)
    with pytest.raises(paper_replay.ReplayError, match="not a redo"):
        replay_redo.compare(db, str(plain.id))
    assert paper_replay.view(db, plain, OPEN)["run"]["redo_of"] is None


def test_starting_before_the_entry_sets_the_clock_there_and_the_link_is_one_event(db):  # noqa: F811
    real = trade(db, opened=datetime(2026, 11, 13, 9, 50), closed=datetime(2026, 11, 13, 10, 20))
    started = replay_redo.start(db, {"trade_id": str(real.id), "start": "before"}, NOW)
    assert started["at"] == OPEN + 5 * 60 and started["redo"]["start"] == "before"  # 09:35
    [link] = db.exec(select(PaperEvent).where(PaperEvent.kind == "redo")).all()
    assert link.position_id == UUID(started["run"]["id"])
    with pytest.raises(paper_replay.ReplayError, match="only goes forward"):  # nothing before the start is traded
        buy(db, paper_replay._run(db, started["run"]["id"]), at(2))
    early = trade(db)
    with pytest.raises(paper_replay.ReplayError, match="starts at the open"):
        replay_redo.start(db, {"trade_id": str(early.id), "start": "before"}, NOW)


def test_the_note_is_built_from_the_facts(db):  # noqa: F811
    real = {"instrument": "option", "quantity": 2.0, "entry": {"at": 1000.0}, "exit": {"at": 9000.0}, "overnight": False}
    side = lambda **k: {"instrument": "option", "trades": 1, "quantity": 2.0, "entry": {"at": 1000.0}, "exit": {"at": 9000.0}, **k}  # noqa: E731
    assert replay_redo.note(real, side()) == "Same entry, exit and size within 5 minutes; only the prices differed."
    assert replay_redo.note(real, side(entry={"at": 1000.0 + 25 * 60}, exit={"at": 9000.0 - 65 * 60})) == "Entered 25 min later, exited 1 h 5 min earlier."
    assert replay_redo.note(real, side(instrument="stock", quantity=50.0)) == "Traded shares instead of the option."
    assert replay_redo.note(real, side(quantity=5.0, trades=2), 1) == "2 trades instead of one, bigger size (5 vs 2 contracts). 1 still open."
    assert replay_redo.note({**real, "overnight": True}, side()) == "Sold the same day (the real one was held overnight)."


def test_redo_my_worst_lists_the_biggest_real_losses_replay_can_play(db, window):  # noqa: F811
    for n, pnl in enumerate([-50.0, -900.0, -10.0, -300.0, -700.0, -20.0]):
        trade(db, ticker=f"A{n}", pnl=pnl)
    trade(db, ticker="WB", pnl=-5000.0, account=WEBULL)  # Webull is dormant
    trade(db, ticker="QUIET", pnl=-4000.0)  # not followed
    trade(db, ticker="WIN", pnl=800.0)
    trade(db, ticker="OPEN", status="open")
    trade(db, ticker="OLD", pnl=-3000.0, opened=datetime(2026, 10, 1, 10), closed=datetime(2026, 10, 1, 11))  # not offered
    window.hidden = {"QUIET"}
    found = replay_redo.worst(db, DAYS)
    assert [w["symbol"] for w in found] == ["A1", "A4", "A3", "A0", "A5"]
    assert found[0] == {"trade_id": found[0]["trade_id"], "day": "2026-11-13", "symbol": "A1", "label": "A1 shares",
                        "instrument": "stock", "pnl": -900.0, "opened_at": found[0]["opened_at"]}
    assert replay_redo.worst(db, []) == []


def test_the_routes_are_owner_only_and_work_end_to_end(db, monkeypatch):  # noqa: F811
    for route in ("GET /copilot/paper/replay/redo", "POST /copilot/paper/replay/redo", "GET /copilot/paper/replay/redo/compare"):
        assert route in DOMAIN_ROUTES
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    monkeypatch.setattr(paper_replay, "days", lambda now: DAYS)
    real = trade(db, pnl=-75.0, opened=datetime(2026, 11, 13, 9, 50), closed=datetime(2026, 11, 13, 10, 20))
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        home = client.get("/copilot/paper/replay", params={"with_days": "true"}).json()
        assert [w["trade_id"] for w in home["worst"]] == [str(real.id)]
        assert "worst" not in client.get("/copilot/paper/replay").json()  # only when he opens replay
        plan = client.get("/copilot/paper/replay/redo", params={"trade_id": str(real.id)}).json()
        assert plan["symbol"] == "NBIS" and plan["before_at"] == OPEN + 5 * 60
        started = client.post("/copilot/paper/replay/redo", json={"trade_id": str(real.id), "start": "before"}).json()
        assert started["at"] == OPEN + 5 * 60
        assert client.post("/copilot/paper/replay/redo", json={"trade_id": str(real.id), "start": "noon"}).status_code == 422
        out = client.get("/copilot/paper/replay/redo/compare", params={"run_id": started["run"]["id"]}).json()
        assert out["difference"] == 75.0 and out["redo"] is None
        assert client.get("/copilot/paper/replay/redo", params={"trade_id": "nope"}).status_code == 400
