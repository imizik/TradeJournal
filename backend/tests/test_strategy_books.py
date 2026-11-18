"""The QQQ strategy books for the copilot and the Friday review (``engine/strategy_books.py``): fixture stores with
known trades give exact bp, $, win rate and the backtest comparison; a book with no file reads "no records", never
zero; a small sample says it is too few to judge; QQQ not followed keeps them silent. Offline, no provider call."""
import asyncio
from datetime import date, datetime

import pytest

from app.ai import copilot, copilot_prompt, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.engine import intraday_momentum_book as ib
from app.engine import overnight_book as ob
from app.engine import paper_review, qqq_paper_coverage, strategy_books
from app.engine.chart_math import ET


def at(day: str, hh: int, mm: int = 0) -> float:
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).timestamp()


FRIDAY = at("2026-11-20", 16, 45)


@pytest.fixture
def books(monkeypatch, tmp_path):
    """Both books on, in temp files: three closed nights (+20, -10, +10 bp), one missed, one held; momentum days +30
    (two trades: +50 and -20), 0, +20 and 0 (one missed check), and today's long still open."""
    monkeypatch.setenv("OVERNIGHT_BOOK_PATH", str(tmp_path / "overnight.sqlite3"))
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_PATH", str(tmp_path / "momentum.sqlite3"))
    monkeypatch.setenv("OVERNIGHT_BOOK_ENABLED", "true")
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_ENABLED", "true")
    monkeypatch.setattr(qqq_paper_coverage, "report", lambda now, receipts, windows: {"missing": 0, "latest_missing_day": None,
                                                                                       "unknown_days": 0})
    o = ob.Store(ob.store_path())
    o.enter("2026-11-16", at("2026-11-16", 15, 59), 599.9, 600.0)
    o.exit("2026-11-16", "2026-11-17", at("2026-11-17", 9, 30), 601.2, 601.3)
    o.enter("2026-11-17", at("2026-11-17", 15, 59), 499.9, 500.0)
    o.exit("2026-11-17", "2026-11-18", at("2026-11-18", 9, 30), 499.5, 499.6)
    o.miss("2026-11-18", "no fresh QQQ quote between 15:59 and 16:00")
    o.enter("2026-11-19", at("2026-11-19", 15, 59), 399.9, 400.0)
    o.exit("2026-11-19", "2026-11-20", at("2026-11-20", 9, 30), 400.4, 400.5)
    o.enter("2026-11-20", at("2026-11-20", 15, 59), 409.9, 410.0)
    m = ib.Store(ib.store_path(), seed=None)
    for day in ("2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"):
        for minute in ib.CHECKS:
            if day == "2026-11-19" and minute == 600:
                m.add_check(day, minute, "missed", note="not reached within five minutes")
            else:
                m.add_check(day, minute, "done", price=500.0)
    m.enter("2026-11-16", 1, 500.0, at("2026-11-16", 10), 501.0)
    m.exit(1, at("2026-11-16", 12), 503.5, "stop")
    m.enter("2026-11-16", -1, 500.0, at("2026-11-16", 13), 503.0)
    m.exit(2, at("2026-11-16", 15, 59), 504.0, "close")
    m.enter("2026-11-18", -1, 500.0, at("2026-11-18", 11), 498.0)
    m.exit(3, at("2026-11-18", 15, 59), 497.0, "close")
    m.add_check("2026-11-20", 600, "done", price=505.0)
    m.enter("2026-11-20", 1, 502.0, at("2026-11-20", 10), 505.0)
    return tmp_path


def test_needed_sample_comes_from_each_backtests_interval():
    # overnight: 2711 x (3.015 / 4.2)^2 = 1397.03 -> 1398; momentum: 1213 x (2.375 / 4.4)^2 = 353.41 -> 354
    assert strategy_books.needed(strategy_books.SPECS["overnight"]) == 1398
    assert strategy_books.needed(strategy_books.SPECS["momentum"]) == 354


def test_known_trades_give_exact_figures_and_a_plain_too_few_read(books):
    out = strategy_books.live(FRIDAY, hidden=set())
    assert out["state"] == "ok" and out["book"] == "strategies" and "never change the rules" in out["note"]
    night, day = out["books"]
    assert night["book"] == "QQQ overnight" and night["state"] == "holding" and night["unit"] == "night"
    assert (night["count"], night["from"], night["to"]) == (3, "2026-11-17", "2026-11-20")
    assert (night["total_bp"], night["total_usd"], night["mean_bp"], night["mean_usd"]) == (20.0, 20.0, 6.67, 6.67)
    assert (night["up"], night["win_rate_pct"]) == (2, 66.7)
    assert night["backtest"] == {"mean_bp": 4.2, "mean_usd": 4.2, "interval_bp": [1.1, 7.13], "sample": 2711,
                                 "years": "2016-2026", "per": "night"}
    assert night["vs_backtest"] == {
        "live_mean_bp": 6.67, "backtest_mean_bp": 4.2, "gap_bp": 2.47, "sample": 3, "needed": 1398,
        "read": "3 nights: too few to judge; it takes roughly 1,398 nights before a live average like the backtest's "
                "+4.2 bp a night could even be told from zero. Live so far +6.67 bp a night."}
    assert night["last"] == {"bought": "2026-11-19", "sold": "2026-11-20", "entry_ask": 400.0, "exit_bid": 400.4,
                             "bp": 10.0, "usd": 10.0}
    assert night["missed"] == [{"day": "2026-11-18", "reason": "no fresh QQQ quote between 15:59 and 16:00"}]
    assert night["holding"] == {"bought": "2026-11-20", "entry_ask": 410.0}

    assert day["book"] == "QQQ intraday momentum" and day["state"] == "holding"
    assert (day["count"], day["trades"], day["from"], day["to"]) == (4, 3, "2026-11-16", "2026-11-19")
    assert (day["total_bp"], day["total_usd"], day["mean_bp"], day["mean_usd"]) == (50.0, 50.0, 12.5, 12.5)
    assert (day["up"], day["win_rate_pct"]) == (2, 50.0)
    assert day["vs_backtest"]["gap_bp"] == 8.1 and day["vs_backtest"]["needed"] == 354
    assert day["vs_backtest"]["read"].startswith("4 days: too few to judge; it takes roughly 354 days")
    assert "one day in five" in day["backtest"]["note"]
    assert day["last"]["side"] == "short" and day["last"]["bp"] == 20.0 and day["last"]["usd"] == 20.0 and day["last"]["how"] == "close"
    assert day["missed"] == [{"day": "2026-11-19", "check": "10:00", "reason": "not reached within five minutes"}]
    assert day["holding"]["side"] == "long" and day["holding"]["entry"] == 505.0
    assert len(copilot_tools.bounded(out)) < copilot_tools.MAX_RESULT_CHARS


def test_a_big_enough_sample_compares_without_the_too_few_line():
    units = [{"day": f"d{i:04d}", "bp": 3.0} for i in range(400)]
    b = strategy_books.report("momentum", units, enabled=True, recorded=True, trades=400)
    assert b["vs_backtest"]["read"] == "Live +3.00 bp a day over 400 days against the backtest's +4.4 bp (-1.40 bp)."
    assert b["total_bp"] == 1200.0 and b["total_usd"] == 1200.0 and b["win_rate_pct"] == 100.0


def test_dollars_follow_the_stake_totals_come_from_unrounded_results_and_losses_keep_their_sign(monkeypatch):
    spec = {**strategy_books.SPECS["overnight"], "stake": 5_000.0}
    monkeypatch.setitem(strategy_books.SPECS, "overnight", spec)
    b = strategy_books.report("overnight", [{"day": "2026-11-17", "bp": -9.98336}, {"day": "2026-11-18", "bp": -20.0}],
                              enabled=True, recorded=True)
    # $5,000 at -29.98336 bp = -$14.99; mean -14.99168 bp = -$7.50 (round half away is not needed: -7.49584)
    assert (b["total_bp"], b["total_usd"], b["mean_bp"], b["mean_usd"]) == (-29.98, -14.99, -14.99, -7.5)
    assert b["win_rate_pct"] == 0.0 and b["vs_backtest"]["gap_bp"] == -19.19
    assert b["vs_backtest"]["read"].endswith("Live so far -14.99 bp a night.")
    tiny = strategy_books.report("overnight", [{"day": "a", "bp": 0.004}, {"day": "b", "bp": 0.004}], enabled=True, recorded=True)
    assert tiny["total_bp"] == 0.01  # from unrounded results: rounding each first would give 0.0
    line = strategy_books.week_line(b, [{"day": "2026-11-17", "bp": -9.98336}, {"day": "2026-11-18", "bp": -20.0}], [],
                                    "2026-11-16", "2026-11-20")
    assert line.startswith("QQQ overnight (paper, $5,000 a night): this week -29.98 bp (-$14.99) over 2 nights; "
                           "running total -29.98 bp (-$14.99) over 2 nights.")


def test_missing_books_read_as_missing_never_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERNIGHT_BOOK_PATH", str(tmp_path / "none-o.sqlite3"))
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_PATH", str(tmp_path / "none-m.sqlite3"))
    monkeypatch.delenv("OVERNIGHT_BOOK_ENABLED", raising=False)
    monkeypatch.delenv("INTRADAY_MOMENTUM_BOOK_ENABLED", raising=False)
    for b in strategy_books.live(FRIDAY, hidden=set())["books"]:
        assert b["state"] == "no records" and b["count"] == 0 and "never switched on" in b["reason"]
        assert all(b[k] is None for k in ("total_bp", "total_usd", "mean_bp", "mean_usd", "win_rate_pct", "last"))
        assert b["vs_backtest"]["gap_bp"] is None and b["vs_backtest"]["read"].startswith("No finished")
    assert not (tmp_path / "none-o.sqlite3").exists()  # reading never creates a book
    # An empty file a switched-off book left behind is still no records, so the review stays silent.
    ob.Store(tmp_path / "none-o.sqlite3")
    ib.Store(tmp_path / "none-m.sqlite3", seed=None)
    assert [b["state"] for b in strategy_books.live(FRIDAY, hidden=set())["books"]] == ["no records", "no records"]
    assert paper_review._strategy_lines(FRIDAY, set()) == []
    assert strategy_books.week_lines(FRIDAY, set()) == [
        "QQQ overnight (paper, $10,000 a night): no records on this server (off or never switched on).",
        "QQQ intraday momentum (paper, $10,000 a day): no records on this server (off or never switched on)."]


def test_qqq_not_followed_keeps_them_silent(books):
    out = strategy_books.live(FRIDAY, hidden={"QQQ"})
    assert out["state"] == "unavailable" and "QQQ" not in out["reason"]
    assert strategy_books.week_lines(FRIDAY, {"QQQ"}) == []


def test_the_friday_lines_give_the_week_the_running_total_and_the_backtest(books, monkeypatch):
    o, m = strategy_books.week_lines(FRIDAY, set())
    assert o == ("QQQ overnight (paper, $10,000 a night): this week +20.00 bp (+$20.00) over 3 nights; 1 missed (no fresh "
                 "QQQ quote between 15:59 and 16:00); running total +20.00 bp (+$20.00) over 3 nights. 3 nights: too few to "
                 "judge; it takes roughly 1,398 nights before a live average like the backtest's +4.2 bp a night could "
                 "even be told from zero. Live so far +6.67 bp a night.")
    assert m.startswith("QQQ intraday momentum (paper, $10,000 a day): this week +50.00 bp (+$50.00) over 4 days; 1 missed "
                        "(10:00 check: not reached within five minutes); running total +50.00 bp (+$50.00) over 4 days. 4 days:")
    # The next week, before anything finishes: no week result, the running total stands.
    monkeypatch.setattr(qqq_paper_coverage, "report", lambda now, receipts, windows: {"missing": 2, "unknown_days": 0,
                                                                                       "latest_missing_day": "2026-11-23"})
    o2, _ = strategy_books.week_lines(at("2026-11-23", 9), set())
    assert "records missing (2 expected record(s) in the last two weeks are missing, latest 2026-11-23" in o2
    assert o2.startswith("QQQ overnight (paper, $10,000 a night): this week no finished nights; running total +20.00 bp")
    for line in (o, m, o2):
        for word in ("should", "change the", "tune", "try "):
            assert word not in line


def test_the_tool_takes_book_strategies_and_nothing_else_with_it():
    assert copilot_tools.validate("get_paper_book", {"book": "strategies"}) == {"book": "strategies"}
    assert copilot_tools.validate("get_paper_book", {"book": "mine"}) == {}
    for bad in ({"book": "strategies", "symbol": "QQQ"}, {"book": "other"}):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_tools.validate("get_paper_book", bad)
    names = [t["name"] for t in copilot_tools.TOOLS]
    assert len(names) == len(set(names)) and "get_strategy_books" not in names  # an option on the paper tool, no new tool
    assert copilot_tools.provenance("get_paper_book", {"book": "strategies"}, "live")["source"] == copilot_tools.STRATEGY_BOOKS_SOURCE
    assert "book strategies" in copilot_prompt.PROMPTS["desk"] and "never suggest changing" in copilot_prompt.PROMPTS["telegram"]
    assert ReplayEvidence.get_paper_book(None, None, "strategies")["state"] == "unavailable"


def test_the_fixture_runs_the_same_arithmetic_and_the_scripted_turn_quotes_it():
    out = FixtureEvidence().get_paper_book(book="strategies")
    assert out["note"].startswith("SIMULATED")
    night, day = out["books"]
    # (601.2-600)/600 = +20 bp, (600.4-601)/601 = -9.98 bp, (599.5-598)/598 = +25.08 bp
    assert night["count"] == 3 and night["total_bp"] == 35.1 and night["win_rate_pct"] == 66.7
    # day 17: (604.4-602)/600 = +40 bp; day 19 short: -(596.9-596)/598 = -15.05 bp; 16 and 18 are 0 days
    assert day["count"] == 4 and day["total_bp"] == 24.95 and day["up"] == 1

    async def turn():
        cfg = copilot.settings()
        return [e async for e in copilot.run_turn([{"role": "user", "content": "How are my strategy books doing?"}], None, cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime.fromtimestamp(FRIDAY, ET))]
    events = asyncio.run(turn())
    assert "get_paper_book" in [e["name"] for e in events if e["type"] == "tool"]
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "QQQ overnight: 3 nights" in text and "too few to judge" in text and "+35.10 bp" in text


def test_a_review_week_without_paper_trades_is_just_the_strategy_lines_with_no_call(books, monkeypatch, tmp_path):
    monkeypatch.setattr(paper_review, "ROOT", tmp_path / "paper_review")
    monkeypatch.setattr(paper_review, "_facts", lambda now: {"day": "2026-11-20", "monday": "2026-11-16", "hidden": set(),
                                                             "paper": None})

    def no_call(*a, **k):
        raise AssertionError("no model call")
    monkeypatch.setattr(paper_review, "_today_count", no_call)
    paper_review.clear()
    entry = asyncio.run(paper_review.write(FRIDAY))
    paper_review.clear()
    assert entry["state"] == "ok" and entry["cost_usd"] == 0.0 and entry["ping"]["state"] == "pending"
    lines = entry["text"].splitlines()
    assert lines[0] == "No closed paper trades of yours this week."
    assert lines[2] == "Strategy books (fixed rules, no money; judged after months):"
    assert lines[3].startswith("- QQQ overnight (paper, $10,000 a night): this week +20.00 bp")
    assert lines[4].startswith("- QQQ intraday momentum (paper, $10,000 a day): this week +50.00 bp")
