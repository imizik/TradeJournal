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

    # The same new anchor twice in one load: one row, the later tag wins, no unique-constraint rollback.
    other = fill(db, "NVDA", "buy_to_open", 1, 200, "2026-09-16T09:44", **CALL)
    key2 = db.get(Fill, other).raw_email_id
    twice = [{**row, "source_key": key2, "tag": {**TAG, "grade": g}} for g in ("B", "A")]
    assert trade_ai_tags.upsert(db, twice, model="claude-opus-5-5", batch_id="b3") == (1, 1)
    assert db.exec(select(TradeAiTag).where(TradeAiTag.source_key == key2)).one().grade == "A"


def test_the_migration_only_adds_the_tag_table(tmp_path):
    path = tmp_path / "tags.sqlite"
    _alembic(path, "upgrade", "a3c7e1f9b2d4")
    engine = sa_create_engine(f"sqlite:///{path}")
    tables = set(inspect(engine).get_table_names())
    assert "trade_ai_tag" not in tables
    _alembic(path, "upgrade", "b7d2f4a9c1e3")
    assert set(inspect(engine).get_table_names()) == tables | {"trade_ai_tag"}
    _alembic(path, "downgrade", "a3c7e1f9b2d4")
    assert set(inspect(engine).get_table_names()) == tables


# --- The tag record the check service shows (pure) ---

from datetime import datetime  # noqa: E402


def _hist(i, pnl, closed="2026-10-01T11:00:00"):
    return {"source_fill_key": f"{i:064x}", "closed_at": closed, "realized_pnl": pnl}


def _tag(i, setup, *, mistakes=(), cut=False):
    return {"source_fill_key": f"{i:064x}", "setup": setup, "primary_mistake": mistakes[0] if mistakes else "none",
            "mistakes": list(mistakes), "broke_cut_rule": cut, "rule_broken_computed": cut, "grade": "C"}


CUTOFF = datetime(2026, 10, 9, 10, 20)
IDEA = {"ticker": "SPY", "side": "long"}


def test_extended_entry_shows_the_chase_record_and_a_fresh_reclaim_shows_the_reclaim_record():
    rows = [_hist(i, -300.0) for i in range(10)] + [_hist(10 + i, 200.0) for i in range(9)]
    rows.append(_hist(99, -5000.0, closed="2026-10-10T11:00:00"))  # closed after the check: never counted
    tags = ([_tag(i, "momentum_chase") for i in range(5)] + [_tag(5 + i, "breakout", mistakes=["chased_extended_entry"])
            for i in range(5)] + [_tag(10 + i, "vwap_reclaim") for i in range(9)] + [_tag(99, "momentum_chase")])
    extended = {"data": {"intraday": {"price_vs_vwap_pct": 3.1, "price": 103.1, "vwap": 100.0, "prev_bar_close": 103.0}}}
    card = trade_ai_tags.pretrade_setup_record(IDEA, extended, rows, tags, CUTOFF, [f"{i:064x}" for i in range(3)], "momentum")
    assert card["matched_setup"] == "momentum_chase" and card["stated_record"]["trades"] == 5
    assert card["lines"][0] == "You called this momentum_chase: your 5 trades tagged momentum_chase lost $1,500 (0 won)."
    chase = next(read for read in card["reads"] if read["read"] == "extended_like_a_chase")
    assert chase["trades"] == 10 and chase["total_pnl"] == -3000.0 and chase["enough"] is True
    assert card["lines"][1].startswith("Price is 3.1% past VWAP, the shape of a chase: your 10 trades tagged as a chase lost $3,000")
    assert card["similar"][0]["setup"] == "momentum_chase" and card["similar"][0]["trades"] == 3
    assert [item["setup"] for item in card["setups"]] == ["breakout", "momentum_chase", "vwap_reclaim"]
    assert card["tagged_trades"] == 19

    reclaim = {"data": {"intraday": {"price_vs_vwap_pct": 0.2, "price": 100.2, "vwap": 100.0, "prev_bar_close": 99.9}}}
    card = trade_ai_tags.pretrade_setup_record(IDEA, reclaim, rows, tags, CUTOFF, [], None)
    assert [read["read"] for read in card["reads"]] == ["fresh_vwap_reclaim"]  # no no-setup tags in this history
    assert card["headline"] == "This is a fresh VWAP reclaim: your 9 trades tagged VWAP reclaim made $1,800 (9 won)."
    # A put idea reads the mirror: below VWAP is "extended" for a short.
    card = trade_ai_tags.pretrade_setup_record({"side": "short"}, extended, rows, tags, CUTOFF, [], None)
    assert card["reads"] == []
    # An unknown or ambiguous name never guesses.
    assert trade_ai_tags.match_setup("chase", ["momentum_chase", "gap_chase"]) is None
    assert trade_ai_tags.pretrade_setup_record(IDEA, {}, rows, tags, CUTOFF, [], "orb")["matched_setup"] is None
    assert trade_ai_tags.pretrade_setup_record(IDEA, {}, rows, None, CUTOFF, [], "orb")["available"] is False
