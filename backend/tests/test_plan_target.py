"""A plan's optional profit target (docs/copilot-lab.md § Confirm a plan): the copilot may draft one, the owner's
Confirm saves it on the plan's capture (``trade_capture.target_price``, a nullable column), the Plans board and the desk
chart carry it as a line with no alert, and the book row hands it to the closing ticket with the plan's stop. A plan
without a target reads exactly as before. The migration only adds the column: no backfill, no existing value changes.
No network."""

import math
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine as sa_create_engine, inspect, text
from sqlmodel import Session

from app.ai import copilot_tools
from app.engine import captures, copilot_investigations, copilot_plans, desk_context, telegram_replies
from app.models import TradeCapture
from app.routers import copilot_desk
from tests import test_telegram
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_desk_context import bars, investigation, lab  # noqa: F401  (fixtures)
from tests.test_copilot_plans import NBIS, ROTH, alert, capture, engine, quotes, time_stop  # noqa: F401  (fixtures)
from tests.test_telegram import Bot, ask_plan, card_data, case, confirm, saved_plan  # noqa: F401  (fixtures)
from tests.test_today import clock  # noqa: F401  (fixture)

BACKEND_DIR = Path(__file__).resolve().parents[1]
BEFORE, AFTER = "b4e8d2a6c1f3", "d7f3b9e5a1c8"

LONG = {"kind": "trade_plan", "symbol": "NBIS", "direction": "long", "instrument": "calls", "thesis": "Holds the base above 95",
        "entry_trigger": {"condition": "crosses", "price": 100.0}, "invalidation": {"condition": "crosses", "price": 95.0}}
SHORT = {**LONG, "direction": "short", "instrument": "puts", "entry_trigger": {"condition": "crosses", "price": 95.0},
         "invalidation": {"condition": "crosses", "price": 100.0}}


def set_target(db_engine, capture_id, price):
    with Session(db_engine) as db:
        row = db.get(TradeCapture, capture_id)
        row.target_price = price
        db.add(row)
        db.commit()


# ------------------------------------------------------------------ the copilot's draft


def test_a_drafted_plan_takes_an_optional_target_on_the_winning_side():
    assert "target_price" not in copilot_tools._proposal(LONG)  # none drafted: the card reads as before
    assert copilot_tools._proposal({**LONG, "target_price": 110.123456})["target_price"] == 110.1235
    assert copilot_tools._proposal({**SHORT, "target_price": 88})["target_price"] == 88.0
    for plan, bad, said in ((LONG, 99.0, "above its entry"), (LONG, 100.0, "above its entry"), (SHORT, 96.0, "below its entry"),
                            (LONG, 0, "positive"), (LONG, -5, "positive"), (LONG, True, "positive"), (LONG, "110", "positive"),
                            (LONG, math.nan, "positive"), (LONG, math.inf, "positive")):
        with pytest.raises(copilot_tools.ToolInputError, match=said):
            copilot_tools._proposal({**plan, "target_price": bad})
    # The tool offers it to the model for plans, beside the practice goal's own (different) target.
    props = next(t for t in copilot_tools.TOOLS if t["name"] == "propose_plan")["input_schema"]["properties"]
    assert props["target_price"]["type"] == "number" and "target" in props


def test_a_saved_card_keeps_its_target_and_an_older_card_without_one_reads_as_it_was():
    with_target = copilot_investigations._saved_proposal({**LONG, "id": "toolu_1", "target_price": 110.0, "last": 98.0})
    assert with_target["target_price"] == 110.0 and with_target["last"] == 98.0
    older = copilot_investigations._saved_proposal({**LONG, "id": "toolu_2", "time_stop": None, "size_note": None, "contract": None})
    assert "target_price" not in older
    # A confirmed card's fields: the target as typed, absent when there is none (as on every card confirmed before).
    fields = {"thesis": "t", "contract": "", "entry": "100", "invalidation": "95", "time_stop": "", "size_note": ""}
    old = copilot_investigations.ProposalOutcome.model_validate({"state": "confirmed", "fields": fields})
    assert "target" not in old.model_dump(exclude_none=True)["fields"]
    new = copilot_investigations.ProposalOutcome.model_validate({"state": "confirmed", "fields": {**fields, "target": "110"}})
    assert new.model_dump(exclude_none=True)["fields"]["target"] == "110"


# ------------------------------------------------------------------ the saved plan


def body(**extra):
    return {"client_id": "card-target-1", "underlying": "NBIS", "account_id": str(ROTH), "side": "buy_calls", "mode": "discretionary",
            "setup_label": "Copilot plan", "wording": "Entry: crosses 100. Invalidation: crosses 95.", "note": "Thesis: x", **extra}


def test_the_plan_capture_saves_its_target_and_a_plan_without_one_saves_none(engine):  # noqa: F811
    with Session(engine) as db:
        saved, _ = captures.save(db, captures.build(db, body(target_price=110.5)))
        plain, _ = captures.save(db, captures.build(db, body(client_id="card-target-2")))
        blank, _ = captures.save(db, captures.build(db, body(client_id="card-target-3", target_price="")))
        assert (saved.target_price, plain.target_price, blank.target_price) == (110.5, None, None)
        assert [r["target_price"] for r in captures.rows(db, [saved, plain])] == [110.5, None]
        for bad in (0, -1, "abc", "nan"):
            with pytest.raises(captures.CaptureError, match="target"):
                captures.build(db, body(client_id="card-target-9", target_price=bad))


def test_the_board_carries_the_saved_target_and_null_without_one(engine):  # noqa: F811
    with_target = capture(engine, "NBIS")
    set_target(engine, with_target, 101.0)
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3)
    other = "22222222-2222-4222-8222-222222222222"
    capture(engine, "CRWV", client_id="card-2")
    alert(engine, other, "CRWV", "entry", 101.0)
    alert(engine, other, "CRWV", "invalidation", 97.0)
    with Session(engine) as db:
        rows = {r["symbol"]: r for r in copilot_plans.board(db, quotes=lambda symbols: ({}, None, None))["plans"]}
    assert rows["NBIS"]["target"] == 101.0 and rows["CRWV"]["target"] is None


def test_the_desk_chart_draws_the_target_line_beside_entry_and_invalidation(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    plan = capture(engine, "NBIS")
    set_target(engine, plan, 99.5)
    time_stop(engine, NBIS, "NBIS")
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, minute=2)
    monkeypatch.setattr(desk_context, "today_minutes", lambda symbol: bars())
    body = lab.get(f"/copilot/desk/{NBIS}/chart").json()
    assert [(level["role"], level["price"], level["label"]) for level in body["levels"]] == [
        ("entry", 95.9, "Entry 95.90"), ("invalidation", 92.3, "Invalidation 92.30"), ("target", 99.5, "Target 99.50")]
    target = body["levels"][2]
    assert target["id"] == f"target:{plan}"  # not an alert: nothing armed at it
    assert body["alerts"] == []


# ------------------------------------------------------------------ Telegram's Confirm, the desk's twin


def test_telegram_shows_and_saves_the_drafted_target(case, monkeypatch):  # noqa: F811
    db_engine, _ = case
    monkeypatch.setattr(test_telegram, "PLAN_EVENT", {**test_telegram.PLAN_EVENT, "target_price": 110.0})
    assert "Target: 110.00" in telegram_replies.plan_text({**test_telegram.PLAN_CARD, "target_price": 110.0}).splitlines()
    assert not any(line.startswith("Target") for line in telegram_replies.plan_text(test_telegram.PLAN_CARD).splitlines())
    bot = Bot()
    ask_plan(db_engine, monkeypatch, bot)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    key = card_data(bot).split(":")[1]
    confirm(db_engine, key)
    _, (saved,), _, _, _, outcome = saved_plan(db_engine, key)
    assert saved.target_price == 110.0
    assert saved.wording == "Entry: crosses 100. Invalidation: 5m close beyond 95. Target: 110. Time stop: out by 15:30."
    assert outcome["fields"]["target"] == "110"


# ------------------------------------------------------------------ the book row's closing-ticket inputs


def test_the_book_row_hands_the_closing_ticket_its_stop_target_and_account():
    row = {"symbol": "NBIS", "instrument": "stock", "account": "Roth IRA ••8267", "unrealized_usd": 10.0,
           "plan": {"invalidation": {"price": 92.3, "state": "armed", "distance_pct": -1.8}}}
    plan = {"entry": {"price": 95.9}, "invalidation": {"price": 92.3}, "target": 101.0, "last": 94.0}
    book = copilot_desk._book(row, plan, None)
    assert book["plan_levels"] == {"stop": 92.3, "target": 101.0} and book["journal_account"] == "Roth IRA ••8267"
    bare = copilot_desk._book({**row, "plan": None}, None, None)
    assert bare["plan_levels"] == {"stop": None, "target": None}  # no plan: no closing ticket


# ------------------------------------------------------------------ the migration


def _alembic(path: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}", "MIGRATION_DATABASE_URL": f"sqlite:///{path}"}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", *args], cwd=BACKEND_DIR, env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_migration_only_adds_a_nullable_column_and_leaves_every_saved_plan_as_it_was(tmp_path):
    path = tmp_path / "target.sqlite"
    _alembic(path, "upgrade", BEFORE)
    db = sa_create_engine(f"sqlite:///{path}")
    row = {"id": "0" * 31 + "1", "client_id": "card-old-plan", "received_at": "2026-11-12 14:00:00", "account_id": "0" * 31 + "2",
           "account_label": "Roth", "underlying": "NBIS", "side": "buy_calls", "instrument": "option", "mode": "discretionary",
           "wording": "Entry: crosses 100. Invalidation: crosses 95.", "strike": 100.0, "quantity": 2.0,
           "context_state": "unavailable", "context_json": "{}", "image_state": "unavailable"}
    with db.begin() as conn:
        conn.execute(text(f"INSERT INTO trade_capture ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"), row)
        before = dict(conn.execute(text("SELECT * FROM trade_capture")).mappings().one())
    _alembic(path, "upgrade", AFTER)
    column = next(c for c in inspect(db).get_columns("trade_capture") if c["name"] == "target_price")
    assert column["nullable"] is True and column["default"] is None
    with db.connect() as conn:
        after = dict(conn.execute(text("SELECT * FROM trade_capture")).mappings().one())
    assert after == {**before, "target_price": None}  # no backfill; nothing else changed
    _alembic(path, "downgrade", BEFORE)
    assert "target_price" not in {c["name"] for c in inspect(db).get_columns("trade_capture")}
    with db.connect() as conn:
        assert dict(conn.execute(text("SELECT * FROM trade_capture")).mappings().one()) == before
    _alembic(path, "upgrade", "head")  # and back up again
    with db.connect() as conn:
        assert conn.execute(text("SELECT target_price FROM trade_capture")).scalar() is None
    db.dispose()

