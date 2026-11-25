"""Model-written trade tags (``app/engine/trade_ai_tags.py``): anchored in the trade's first entry fill so a rebuild
keeps them, replaced (not duplicated) on a second load, never touching trades or fills; the migration only adds a
table. No network."""

from sqlalchemy import create_engine as sa_create_engine, inspect
from sqlmodel import select

from app.engine import trade_ai_tags
from app.models import Fill, Trade, TradeAiTag
from app.routers.fills import _rebuild_trades
from tests.test_capture_links import CALL, ROTH, db, fill, trade_of  # noqa: F401  (fixtures and helpers)
from tests.test_plan_target import _alembic

TAG = {"setup": "dip_buy_reversal", "mistakes": ["held_loser_past_cut", "averaged_down"], "primary_mistake": "held_loser_past_cut",
       "broke_cut_rule": True, "grade": "D", "rationale": "Held down 40% past 11:00.", "confidence": 0.8}


def test_a_tag_follows_its_trade_through_a_rebuild_and_a_reload_replaces_it(db):  # noqa: F811
    entry = fill(db, "NVDA", "buy_to_open", 2, 300, "2026-09-15T09:44", **CALL)
    fill(db, "NVDA", "sell_to_close", 2, 120, "2026-09-15T11:30", **CALL)
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    key = db.get(Fill, entry).raw_email_id
    before = [(t.id, t.realized_pnl) for t in db.exec(select(Trade)).all()]
    row = {"account_id": str(ROTH), "source_key": key, "trade_id": str(trade.id), "tag": TAG,
           "facts": {"rule_broken_computed": True, "dte_at_open": 0}}
    assert trade_ai_tags.upsert(db, [row], model="claude-opus-5-5", batch_id="b1") == (1, 0)
    assert [(t.id, t.realized_pnl) for t in db.exec(select(Trade)).all()] == before  # nothing else written
    got = trade_ai_tags.for_trades(db, [trade.id])[str(trade.id)]
    assert got["setup"] == "dip_buy_reversal" and got["mistakes"] == ["held_loser_past_cut", "averaged_down"]
    assert got["broke_cut_rule"] is True and got["rule_broken_computed"] is True

    _rebuild_trades(db, "test")  # new trade ids; the tag still finds its trade through the fill
    rebuilt = trade_of(db, entry)
    assert trade_ai_tags.for_trades(db, [rebuilt.id])[str(rebuilt.id)]["grade"] == "D"

    assert trade_ai_tags.upsert(db, [{**row, "tag": {**TAG, "grade": "C"}}], model="claude-opus-5-5", batch_id="b2") == (0, 1)
    [only] = db.exec(select(TradeAiTag)).all()
    assert only.grade == "C" and only.batch_id == "b2"
    assert trade_ai_tags.for_trades(db, []) == {}


def test_the_migration_only_adds_the_tag_table(tmp_path):
    path = tmp_path / "tags.sqlite"
    _alembic(path, "upgrade", "a3c7e1f9b2d4")
    db = sa_create_engine(f"sqlite:///{path}")
    tables = set(inspect(db).get_table_names())
    assert "trade_ai_tag" not in tables
    _alembic(path, "upgrade", "b7d2f4a9c1e3")
    assert set(inspect(db).get_table_names()) == tables | {"trade_ai_tag"}
    _alembic(path, "downgrade", "a3c7e1f9b2d4")
    assert set(inspect(db).get_table_names()) == tables
