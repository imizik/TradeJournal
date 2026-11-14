"""One-line notes on a trade from the desk (``app/engine/trade_notes.py``): saved with the trade as
``TradeCaptureNote`` rows, on its linked plan when it has one and anchored in its first fill either way. A note is never
a plan: it creates no capture and no link, and a plan still links afterwards. Notes never change fills, trades or P&L,
reach the day report, the copilot's thesis and the day journal, and the migration only adds nullable columns. No
network."""

from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine as sa_create_engine, inspect, text
from sqlmodel import select

from app.ai import copilot_context
from app.database import get_session
from app.engine import capture_links, day_report, plan_streak, trade_notes, trader_context
from app.models import CaptureLink, Fill, Trade, TradeCapture, TradeCaptureNote
from app.routers import captures as captures_router
from app.routers import copilot_desk, day_journal as day_journal_router
from app.routers.fills import _rebuild_trades
from tests.test_capture_links import CALL, OTHER, ROTH, capture, db, fill, trade_of  # noqa: F401  (fixtures and helpers)
from tests.test_plan_target import _alembic


@pytest.fixture
def desk(db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    app = FastAPI()
    app.include_router(copilot_desk.router, prefix="/copilot")
    app.include_router(captures_router.router, prefix="/charts")
    app.include_router(day_journal_router.router, prefix="/day-journal")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        yield client


def snapshot(db):  # noqa: F811
    trades = [(t.id, t.status, t.realized_pnl, t.opened_at, t.closed_at) for t in db.exec(select(Trade)).all()]
    fills = [(f.id, f.price, f.contracts, f.side) for f in db.exec(select(Fill)).all()]
    return sorted(trades, key=str), sorted(fills, key=str)


def test_a_note_on_a_trade_with_no_plan_is_not_a_plan_and_a_plan_still_links_afterwards(db, desk):  # noqa: F811
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    before = snapshot(db)
    saved = desk.post("/copilot/desk/notes", json={"trade_id": str(trade.id), "text": "  Bought the reclaim of 905\n on volume "})
    assert saved.status_code == 200, saved.text
    assert saved.json()["note"]["text"] == "Bought the reclaim of 905 on volume"  # one line
    # No capture, no link: the trade has no plan, counts as unplanned, and the companion and linker still see it so.
    assert db.exec(select(TradeCapture)).all() == [] and db.exec(select(CaptureLink)).all() == []
    assert capture_links.for_trade(db, trade.id) == []
    [note] = db.exec(select(TradeCaptureNote)).all()
    assert note.capture_id is None and note.kind == "note" and note.account_id == ROTH and note.source_key.startswith("links:")
    assert snapshot(db) == before  # fills, trades and P&L untouched
    # A plan links afterwards as before; the note stays with the trade, and a later note goes on the plan too.
    plan = capture(db, "2026-09-15T13:40:00")
    capture_links.link(db, plan, trade.id)
    desk.post("/copilot/desk/notes", json={"trade_id": str(trade.id), "text": "Trimmed into the high"})
    notes = desk.get("/copilot/desk/notes", params={"trade": str(trade.id)}).json()["trades"][str(trade.id)]
    assert [n["text"] for n in notes] == ["Bought the reclaim of 905 on volume", "Trimmed into the high"]
    on_plan = desk.get(f"/charts/captures/for-trade/{trade.id}").json()["captures"][0]["notes"]
    assert [n["text"] for n in on_plan] == ["Trimmed into the high"]


def test_a_note_on_a_planned_trade_is_the_plans_note_and_is_listed_once(db, desk):  # noqa: F811
    plan = capture(db, "2026-09-15T13:40:00")
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    capture_links.link(db, plan, trade.id)
    desk.post("/copilot/desk/notes", json={"trade_id": str(trade.id), "text": "Why I'm in: the base held"})
    # A note written on the plan sheet (the Journal) shows on the desk too, once.
    desk.post(f"/charts/captures/{plan.id}/notes", json={"kind": "note", "text": "From the plan sheet"})
    [note] = [n for n in db.exec(select(TradeCaptureNote)).all() if n.source_key]
    assert note.capture_id == plan.id
    notes = desk.get("/copilot/desk/notes", params={"trade": str(trade.id)}).json()["trades"][str(trade.id)]
    assert [n["text"] for n in notes] == ["Why I'm in: the base held", "From the plan sheet"]


def test_notes_stay_with_the_trade_when_a_rebuild_moves_its_first_fill(db, desk):  # noqa: F811
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    desk.post("/copilot/desk/notes", json={"trade_id": str(trade_of(db, entry).id), "text": "Starter"})
    fill(db, "NVDA", "buy_to_open", 1, 300, "2026-09-15T09:38", **CALL)  # a delayed earlier fill: a new first entry
    _rebuild_trades(db, "rebuild")
    moved = trade_of(db, entry)
    assert moved.id != entry
    assert [n["text"] for n in desk.get("/copilot/desk/notes", params={"trade": str(moved.id)}).json()["trades"][str(moved.id)]] == ["Starter"]


def test_a_fill_line_finds_its_trade_by_contract_and_one_not_in_the_journal_yet_is_refused(db, desk):  # noqa: F811
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    fill(db, "NVDA", "sell_to_close", 1, 330, "2026-09-15T11:00", **CALL)
    fill(db, "AMD", "buy", 10, 150, "2026-09-15T10:00")
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    contract = "NVDA 1/15/99 900C"
    saved = desk.post("/copilot/desk/notes", json={"symbol": "NVDA", "contract": contract, "text": "Why I left: lost VWAP"})
    assert saved.status_code == 200 and saved.json()["trade_id"] == str(trade.id)
    key = f"NVDA|{contract}|••8267"
    body = desk.get("/copilot/desk/notes", params={"fill": [key, "AMD|AMD stock|••8267", "TSLA|TSLA stock|••8267", "AMD|AMD stock|••0000"]}).json()
    assert body["fills"] == {key: str(trade.id), "AMD|AMD stock|••8267": str(trade_of(db, UUID(int=entry.int + 2)).id),
                             "TSLA|TSLA stock|••8267": None, "AMD|AMD stock|••0000": None}  # no such account: no trade
    assert [n["text"] for n in body["trades"][str(trade.id)]] == ["Why I left: lost VWAP"]
    refused = desk.post("/copilot/desk/notes", json={"symbol": "TSLA", "contract": "TSLA stock", "text": "new buy"})
    assert refused.status_code == 409 and "does not have this fill yet" in refused.json()["detail"]


def test_a_note_must_be_one_short_line_and_the_routes_wait_for_the_lab(db, desk, monkeypatch):  # noqa: F811
    entry = fill(db, "AMD", "buy", 10, 150, "2026-09-15T10:00")
    _rebuild_trades(db, "test")
    trade_id = str(trade_of(db, entry).id)
    assert desk.post("/copilot/desk/notes", json={"trade_id": trade_id, "text": "  \n "}).status_code == 422
    assert desk.post("/copilot/desk/notes", json={"trade_id": trade_id, "text": "x" * (trade_notes.MAX + 1)}).status_code == 422
    assert desk.post("/copilot/desk/notes", json={"trade_id": str(UUID(int=999_999)), "text": "gone"}).status_code == 422
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.post("/copilot/desk/notes", json={"trade_id": trade_id, "text": "hi"}).status_code == 503
    assert desk.get("/copilot/desk/notes").status_code == 503
    assert db.exec(select(TradeCaptureNote)).all() == []


def test_the_day_report_the_copilot_thesis_and_the_day_journal_carry_the_notes(db, desk, monkeypatch):  # noqa: F811
    entry = fill(db, "AMD", "buy", 10, 150, "2026-09-15T10:00")
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    trade_notes.add(db, trade.id, "Why I'm in: gap fill")
    # The day report lists the notes beside the entry.
    at = 1_789_000_000
    week = {"this_week": {"entries": [{"trade_id": str(trade.id), "short": "AMD stock", "state": "unplanned", "entry_time": at}]}}
    monkeypatch.setattr(plan_streak, "streak", lambda db: week)
    from datetime import date
    rows = day_report.entries_today(db, date.fromtimestamp(at), set())["rows"]
    assert rows[0]["notes"] == ["Why I'm in: gap fill"]
    # The copilot's thesis for the position: no plan, but his note is in its revisions and reaches the pack.
    thesis = trader_context.thesis_for(db, trade, adopted={}, horizons={})
    assert thesis["source"] == "none" and [r["text"] for r in thesis["revisions"]] == ["Why I'm in: gap fill"]
    plan = copilot_context._plan(thesis)
    assert plan["source"] == "none" and plan["revisions"][0].endswith("owner: Why I'm in: gap fill")
    assert copilot_context._plan({**thesis, "revisions": []}) == {"source": "none"}
    # The day journal shows a no-plan trade's notes (a plan's own notes already show under the plan).
    journal = desk.get("/day-journal/2026-09-15").json()
    assert journal["trade_notes"] == [{"trade_id": str(trade.id), "contract": "AMD stock",
                                       "notes": [{"id": journal["trade_notes"][0]["notes"][0]["id"], "text": "Why I'm in: gap fill",
                                                  "at": journal["trade_notes"][0]["notes"][0]["at"]}]}]


def test_a_planned_trades_thesis_lists_a_desk_note_once(db):  # noqa: F811
    plan = capture(db, "2026-09-15T13:40:00")
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    capture_links.link(db, plan, trade.id)
    trade_notes.add(db, trade.id, "Holding through lunch")
    thesis = trader_context.thesis_for(db, trade, adopted={}, horizons={})
    assert [r["text"] for r in thesis["revisions"]] == ["Holding through lunch"]


def test_the_migration_only_adds_nullable_columns_and_keeps_every_note(tmp_path):
    path = tmp_path / "notes.sqlite"
    _alembic(path, "upgrade", "c5e9a3d7f1b4")
    store = sa_create_engine(f"sqlite:///{path}")
    capture_row = {"id": "0" * 31 + "1", "client_id": "plan-old", "received_at": "2026-11-12 14:00:00", "account_id": "0" * 31 + "2",
                   "account_label": "Roth", "underlying": "NBIS", "side": "buy_calls", "instrument": "option", "mode": "discretionary",
                   "context_state": "unavailable", "context_json": "{}", "image_state": "unavailable"}
    note_row = {"id": "0" * 31 + "3", "capture_id": "0" * 31 + "1", "kind": "note", "text": "old", "created_at": "2026-11-12 15:00:00"}
    with store.begin() as conn:
        for table, row in (("trade_capture", capture_row), ("trade_capture_note", note_row)):
            conn.execute(text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"), row)
        before = dict(conn.execute(text("SELECT * FROM trade_capture_note")).mappings().one())
    _alembic(path, "upgrade", "e2c6a8f4b1d9")
    columns = {c["name"]: c for c in inspect(store).get_columns("trade_capture_note")}
    assert columns["capture_id"]["nullable"] and columns["account_id"]["nullable"] and columns["source_key"]["nullable"]
    with store.begin() as conn:
        assert dict(conn.execute(text("SELECT * FROM trade_capture_note")).mappings().one()) == {**before, "account_id": None, "source_key": None}
        conn.execute(text("INSERT INTO trade_capture_note (id, capture_id, kind, text, created_at, source_key) "
                          "VALUES (:id, NULL, 'note', 'desk', '2026-11-13 15:00:00', 'k1')"), {"id": "0" * 31 + "4"})
    _alembic(path, "downgrade", "c5e9a3d7f1b4")  # a note with no plan cannot stay; every plan's note does
    with store.connect() as conn:
        assert [dict(r) for r in conn.execute(text("SELECT * FROM trade_capture_note")).mappings()] == [before]
    _alembic(path, "upgrade", "head")
    store.dispose()


def test_a_fill_line_never_takes_the_same_contract_in_another_account(db, desk):  # noqa: F811
    other = fill(db, "AMD", "buy", 10, 150, "2026-09-14T10:00", account=OTHER)  # still open in the other account
    mine = fill(db, "AMD", "buy", 5, 151, "2026-09-15T10:00")
    fill(db, "AMD", "sell", 5, 155, "2026-09-15T11:00")  # the Roth's closing fill: its line sits in the Orders group
    _rebuild_trades(db, "test")
    roth, elsewhere = trade_of(db, mine), trade_of(db, other)
    assert elsewhere.status == "open" and roth.status == "closed"
    body = desk.get("/copilot/desk/notes", params={"fill": ["AMD|AMD stock|••8267", "AMD|AMD stock|••1111"]}).json()
    assert body["fills"] == {"AMD|AMD stock|••8267": str(roth.id), "AMD|AMD stock|••1111": str(elsewhere.id)}
    saved = desk.post("/copilot/desk/notes", json={"symbol": "AMD", "contract": "AMD stock", "account": "••8267", "text": "Why I left"})
    assert saved.json()["trade_id"] == str(roth.id)


def test_a_desk_note_stays_with_its_trade_when_the_plan_is_relinked(db, desk):  # noqa: F811
    plan = capture(db, "2026-09-15T13:40:00")
    first = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    fill(db, "NVDA", "sell_to_close", 1, 320, "2026-09-15T09:50", **CALL)
    second = fill(db, "NVDA", "buy_to_open", 1, 300, "2026-09-15T10:30", **CALL)
    _rebuild_trades(db, "test")
    a, b = trade_of(db, first), trade_of(db, second)
    assert a.id != b.id
    capture_links.link(db, plan, a.id)
    trade_notes.add(db, a.id, "Why I left A: lost VWAP")
    capture_links.unlink(db, plan)
    capture_links.link(db, plan, b.id)
    notes = trade_notes.for_trades(db, [a.id, b.id])
    assert [n["text"] for n in notes[str(a.id)]] == ["Why I left A: lost VWAP"] and str(b.id) not in notes
    assert trader_context.thesis_for(db, b, adopted={}, horizons={})["revisions"] == []
    assert [r["text"] for r in trader_context.thesis_for(db, a, adopted={}, horizons={})["revisions"]] == ["Why I left A: lost VWAP"]
