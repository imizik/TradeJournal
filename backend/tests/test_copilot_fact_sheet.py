"""get_fact_sheet: one symbol's price, volume, tape, implied move, catalysts, peers, record and position. Pure; no network."""
from datetime import datetime

from app.ai import copilot_fact_sheet as fs, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_tool_summary import summarize
from app.engine.chart_math import ET

NOW = datetime(2026, 11, 27, 10, 15, tzinfo=ET)
QUOTES = {"state": "ok", "quotes": {"NBIS": {"last": 90.0, "change_pct": -5.0, "trade_time": "t"},
                                    "SPY": {"change_pct": 0.3}, "QQQ": {"change_pct": 0.5}}}
CHART = {"state": "ok", "last": 90.0, "vwap": {"vwap": 92.0},
         "levels": {"atr": 3.0, "at": [], "above": [{"low": 91.0, "high": 91.5, "label": "VWAP-ish", "state": "tested"}],
                    "below": [{"low": 88.0, "high": 88.2, "label": "Prior day low", "state": "untested"}]},
         "rvol": {"state": "ready", "last_bar": 2.4},
         "quote": {"open": 91.0, "previous_close": 94.74, "day_high": 92.5, "day_low": 89.6, "volume": 5_000_000}}
FORECAST = {"source": "Tradier", "moves": [
    {"tags": ["nearest"], "expiration": "2026-11-28", "days": 1, "state": "ready", "strike": 90.0, "move": 2.7,
     "percent": 0.03, "iv": 0.9, "call": {"bid": 1.2, "ask": 1.5}, "put": {"bid": 1.3, "ask": 1.4}},
    {"tags": ["friday"], "expiration": "2026-12-04", "days": 7, "state": "too_wide", "reason": "no bid"}]}
CATALYSTS = {"state": "ok", "since": "11-26 16:00 ET", "sources": {"sec_filings": "ok", "halts": "unavailable: x", "headlines": "ok"},
             "items": [{"type": "headline", "title": "h"}, {"type": "filing", "form": "424B5"}, {"type": "headline", "title": "old"}],
             "unexplained_moves": []}
PEERS = {"peers": [{"symbol": "CRWV", "change_pct": -3.0}, {"symbol": "APLD", "change_pct": 1.0}, {"symbol": "X", "change_pct": None}]}
RECORD = {"state": "ok", "trades": 20, "win_rate": 0.4, "total_pnl": -900.0, "median_pnl": -40.0, "broke_cut_rule": 6,
          "small_sample": False, "setups": [{"setup": "gap_fade", "total_pnl": -500}, {"setup": "vwap_reclaim", "total_pnl": 300}],
          "top_mistakes": [{"mistake": "chased", "total_pnl": -200}, {"mistake": "held_past_cut", "total_pnl": -700}]}
BOOK = {"state": "ok", "positions": [
    {"symbol": "NBIS", "instrument": "option", "direction": "long", "quantity": 3, "avg_entry": 200.0, "mark": 130.0,
     "unrealized_usd": -210.0, "unrealized_pct": -35.0, "option": {"side": "call", "strike": 95.0, "expiry": "2026-11-28"},
     "_cut": 140.0},
    {"symbol": "CRWV", "instrument": "stock", "direction": "long", "quantity": 10}]}


def _sheet(**over):
    parts = dict(quotes=QUOTES, chart=CHART, forecast=FORECAST, premarket=None, catalyst=CATALYSTS, peer=PEERS, mine=RECORD,
                 book=BOOK)
    return fs.assemble("NBIS", NOW, **{**parts, **over})


def test_every_section_reads_from_its_source():
    out = _sheet()
    assert out["state"] == "ok" and out["missing"] == [] and out["as_of"] == "2026-11-27T10:15-05:00"
    assert out["price"]["gap_pct"] == -3.95 and out["price"]["change_pct"] == -5.0 and out["price"]["volume"] == 5_000_000
    assert out["volume"]["rvol"] == 2.4 and "rvol" not in out["tape"]
    assert out["tape"]["vs_vwap_pct"] == -2.17 and out["tape"]["level_above"]["distance_pct"] == 1.11
    assert out["tape"]["level_below"]["distance_pct"] == -2.0
    near, friday = out["implied_move"]["expirations"]
    assert (near["move_pct"], near["call_spread_pct"], near["put_spread_pct"], near["iv"]) == (3.0, 22.2, 7.4, 90.0)
    assert friday == {"expiration": "2026-12-04", "days": 7, "tags": ["friday"], "state": "too_wide", "reason": "no bid"}
    assert out["catalysts"]["counts"] == {"filing": 1, "halt": 0, "headline": 2}
    assert out["catalysts"]["newest_primary"]["form"] == "424B5" and out["catalysts"]["newest_headline"]["title"] == "h"
    assert out["catalysts"]["unavailable"] == {"halts": "unavailable: x"}
    assert out["peers"] == {"market": {"SPY": 0.3, "QQQ": 0.5}, "up": 1, "of": 2, "median_pct": -1.0,
                            "leader": {"symbol": "APLD", "change_pct": 1.0}, "laggard": {"symbol": "CRWV", "change_pct": -3.0}}
    assert out["my_record"]["best_setup"]["setup"] == "vwap_reclaim" and out["my_record"]["worst_mistake"]["mistake"] == "held_past_cut"


def test_a_short_dated_red_option_carries_its_cut_line():
    (pos,) = _sheet()["position"]
    assert pos["cut_line"] == 140.0 and pos["mark_vs_cut_pct"] == -7.14 and pos["past_cut"] is True
    assert pos["days_to_expiry"] == 1 and pos["short_dated_red"] is True


def test_a_longer_dated_or_green_option_is_not_flagged():
    book = {"state": "ok", "positions": [{**BOOK["positions"][0], "option": {"side": "call", "strike": 95.0, "expiry": "2026-12-18"},
                                          "_cut": None}, {**BOOK["positions"][0], "unrealized_pct": 4.0, "_cut": None}]}
    longer, green = _sheet(book=book)["position"]
    assert "short_dated_red" not in longer and "cut_line" not in longer and "short_dated_red" not in green


def test_a_failed_section_is_named_and_never_hides_the_rest():
    out = _sheet(forecast=None, catalyst={"state": "unavailable"}, book={"state": "unavailable"})
    assert out["state"] == "partial" and out["missing"] == ["position", "implied_move", "catalysts"]
    assert out["price"]["last"] == 90.0


def test_pre_market_volume_replaces_rvol_before_the_open():
    pace = {"state": "ok", "kind": "pre-market", "volume": 2000, "typical": 100, "pace_x": 20.0}
    out = _sheet(premarket=pace, chart={**CHART, "rvol": {"state": "waiting"}})
    assert out["volume"] == pace and out["tape"]["rvol_state"] == "waiting"


def test_fixture_is_simulated_and_reads_as_one_line():
    data = FixtureEvidence().get_fact_sheet("NBIS")
    assert data["simulated"] is True and data["note"] == fs.FIXTURE_NOTE and data["missing"] == []
    assert summarize("get_fact_sheet", data) == ("NBIS 94.35 -2.95%, gap -0.43%, RVOL 1.3, implied ±3.29% (1d), "
                                                 "1 filing or halt, 1 headline")


def test_the_tool_is_listed_and_kept_off_research_jobs():
    from app.ai import research_job
    assert "get_fact_sheet" in {t["name"] for t in copilot_tools.TOOLS}
    assert "journal" in copilot_tools.PROVENANCE["get_fact_sheet"][0]
    assert "get_fact_sheet" not in research_job.JOB_TOOLS
    assert copilot_tools.validate("get_fact_sheet", {"symbol": "nbis"}) == {"symbol": "NBIS"}


def test_desk_and_phone_prompts_read_the_fact_sheet_first_and_shape_a_deep_read():
    from app.ai import copilot, copilot_prompt as cp
    for job in (cp.DESK, cp.TELEGRAM):
        prompt = " ".join(cp.system_prompt(job).split())
        assert "call get_fact_sheet first" in prompt and 'is never answered with hold or wait' in prompt
        assert '"Deep read <symbol>" asks for the full read now' in prompt and "may run to 250 words" in prompt
    for job in (cp.PREP, cp.COMPANION, cp.DESK_READ):
        assert "get_fact_sheet" not in cp.system_prompt(job)
    assert "get_fact_sheet" in copilot.DEEP_TOOLS  # the read itself opens the deep turn's room


def test_the_fact_line_never_counts_a_failed_catalyst_feed_as_zero():
    line = summarize("get_fact_sheet", _sheet())
    assert line.startswith("NBIS 90 -5%, past cut line, gap -3.95%") and "catalysts partial" in line  # halts were down


def test_live_reads_share_one_deadline_and_a_slow_one_is_only_missing(monkeypatch):
    import threading
    from app.ai import copilot_extended
    from app.engine.options_feed import options_feed
    release = threading.Event()
    fixture = FixtureEvidence()

    class Slow(FixtureEvidence):
        def get_catalysts(self, symbol):  # a cold SEC ticker list
            release.wait(5)
            return fixture.get_catalysts(symbol)
    monkeypatch.setattr(fs, "READ_DEADLINE", 0.3)
    monkeypatch.setattr(fs, "live_book", lambda symbol: fixture.get_positions())
    monkeypatch.setattr(copilot_extended, "premarket_pace", lambda symbol, now: None)
    monkeypatch.setattr(options_feed, "forecast", lambda symbol, spot, earnings: FORECAST if spot == 94.35 else None)
    try:
        out = fs.live_sheet(Slow(), "NBIS")
    finally:
        release.set()
    assert out["missing"] == ["catalysts"] and out["implied_move"]["expirations"][0]["move_pct"] == 3.0
    assert out["price"]["last"] == 94.35 and out["my_record"]["trades"] == 14


def test_each_position_keeps_its_own_cut_line_and_the_symbol_is_read_ahead_of_the_book_limit(monkeypatch):
    """The same contract in two accounts at $100 and $200 keeps two cut lines, and 16 other open positions that sort
    first never push the symbol out of the read."""
    from datetime import date
    from uuid import UUID
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine
    import app.database
    from app.engine import quotes
    from app.engine.quotes import OptionQuoteResult
    from app.models import Account, Fill
    from app.routers.fills import _rebuild_trades
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    one, two = UUID(int=1), UUID(int=2)
    call = {"option_type": "call", "strike": 95, "expiration": date(2026, 11, 28)}
    with Session(engine) as db:
        db.add(Account(id=one, name="Robinhood 1111", type="individual", last4="1111", broker="robinhood"))
        db.add(Account(id=two, name="Robinhood 2222", type="roth_ira", last4="2222", broker="robinhood"))
        db.add_all([Fill(id=UUID(int=10), account_id=one, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                         price=100, executed_at=datetime(2026, 11, 26, 10, 0), raw_email_id="fs:10", **call),
                    Fill(id=UUID(int=11), account_id=two, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                         price=200, executed_at=datetime(2026, 11, 26, 10, 5), raw_email_id="fs:11", **call)])
        db.add_all([Fill(id=UUID(int=100 + i), account_id=one, ticker=f"A{i:02d}", instrument_type="stock", side="buy", contracts=1,
                         price=10, executed_at=datetime(2026, 11, 20, 10, 0), raw_email_id=f"fs:{100 + i}") for i in range(16)])
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
    monkeypatch.setattr(app.database, "engine", engine)
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: 10.0 for s in symbols})
    monkeypatch.setattr(quotes, "option_mark", lambda req: (OptionQuoteResult(mid=1.0, last_price=1.0), 1792768320.0))
    book = fs.live_book("NBIS")
    assert sorted(p["_cut"] for p in book["positions"]) == [70.0, 140.0] and "incomplete" not in book
    rows = fs.position("NBIS", book, date(2026, 11, 27))
    assert {(r["avg_entry"], r["cut_line"], r["past_cut"]) for r in rows} == {(100.0, 70.0, False), (200.0, 140.0, True)}
    engine.dispose()


def test_a_large_book_fits_the_result_with_the_risky_positions_first():
    risky = BOOK["positions"][0]
    calm = {**risky, "unrealized_pct": 5.0, "mark": 210.0, "_cut": None,
            "option": {"side": "put", "strike": 80.0, "expiry": "2027-01-15"}}
    book = {"state": "ok", "positions": [calm] * 14 + [risky]}
    long_title = "T" * 200
    catalyst = {**CATALYSTS, "items": [{"type": "headline", "title": long_title, "url": "https://x/" + "u" * 150,
                                        "reaction": {"move_15m_pct": 1.0, "volume_x": 2.0}},
                                       {"type": "filing", "form": "8-K", "title": long_title, "detail": "Item 2.02, Item 9.01",
                                        "url": "https://y/" + "u" * 150, "reaction": {"move_15m_pct": 1.0, "volume_x": 2.0}}],
                "unexplained_moves": [{"at": "11-27 09:31 ET", "move_5m_pct": 2.0, "volume_x": 9.0}] * 3,
                "note": "n" * 120, "headlines_from": "11-27 08:00 ET"}
    out = _sheet(book=book, catalyst=catalyst, chart={**CHART, "delayed": True, "provider": "Alpaca SIP"})
    text = copilot_tools.bounded(out)
    assert "[truncated]" not in text and len(text) <= copilot_tools.MAX_RESULT_CHARS
    assert len(out["position"]) == fs.MAX_POSITIONS_SHOWN and out["position"][0]["past_cut"] is True
    assert out["position_omitted"] == "9 more open positions in NBIS not shown"
    assert out["delayed"]["provider"] == "Alpaca SIP" and list(out)[:4] == ["symbol", "state", "as_of", "missing"]
