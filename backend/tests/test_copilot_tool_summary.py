"""The copilot's fact lines: one deterministic line per tool result for the wait before the answer. Pure; no network."""
import asyncio

import pytest

from app.ai import copilot
from app.ai.copilot_fixture import OPEN_REVIEW_ID, FixtureEvidence
from app.ai.copilot_tool_summary import MAX_CHARS, summarize
from tests.test_copilot import NOW, _cfg

E = FixtureEvidence()


@pytest.mark.parametrize("name,args,expected", [
    ("get_group_comparison", {"symbol": "NBIS"}, "NBIS +0.84% vs SPY +0.09%, 4 of 6 peers up (15m, 11:12)"),
    ("get_peer_moves", {"symbol": "NBIS"}, "Peers: 1 of 6 up, APLD leads +0.85%"),
    ("get_symbol_news", {"symbol": "NBIS"}, "3 headlines since 08:10, latest 10:40"),
    ("get_quotes", {"symbols": ["NBIS", "SPY"]}, "NBIS 94.35 -2.95%, SPY 671.1 -0.2% (11:12)"),
    ("get_option_candidates", {"symbol": "NBIS", "horizon_days": 30, "direction": "long"},
     "8 calls: NBIS Nov 20 95C ask 7.99, IV 75%, Δ 0.528"),
    ("get_market_regime", {"symbol": "NBIS"}, "Regime: SPY -0.2%, QQQ -0.35%, VIX 18.4, 10y 4.12%, NBIS -2.47% vs XLK (11:12)"),
    ("get_radar_today", {}, "Radar today: 3 events, 2 on CRWV, latest 10:58"),
    ("get_breadth", {}, "S&P 500 breadth: 188 up, 309 down, median -0.41%, 9 highs / 14 lows"),
    ("get_positioning", {"symbol": "NBIS"}, "VIX 19.1 (mixed), NBIS ATM IV 18.4%, skew 7.3, P/C vol 1.42"),
    ("get_macro", {}, "FRED: 10y 4.96%, 2y 4.31%, HY spread 3.31%, NFCI -0.48 (Oct 22)"),
    ("get_base_rates", {"symbol": "NBIS"}, "7 drops of 21%+ since 2020, 63d median -30.55%"),
    ("get_trade_review", {"trade_id": OPEN_REVIEW_ID}, "NBIS 11/21/26 100C open -$310 (-25.4%), 1 alert"),
    ("get_trade_review", {"trade_id": "closed"}, "NBIS 11/21/26 100C closed -$110 (-17.7%), 1 alert"),
    ("get_symbol_profile", {"symbol": "NBIS"}, "NBIS: earnings Nov 12 (estimated), short 13.2% of shares, cap 22.4B"),
    ("get_symbol_events", {"symbol": "NBIS"}, "NBIS earnings Nov 12 (estimated)"),
])
def test_fixture_results_read_as_one_fact(name, args, expected):
    assert summarize(name, getattr(E, name)(**args)) == expected


def test_web_search_counts_results():
    assert summarize("web_search", {"results": 3}) == "Web: 3 results"
    assert summarize("web_search", {"results": 1}) == "Web: 1 result"


def test_headlines_are_counted_never_quoted():
    data = E.get_symbol_news("NBIS")
    line = summarize("get_symbol_news", data)
    assert all(a["headline"] not in line and a["publisher"] not in line for a in data["articles"])
    assert "Ignore" not in line


@pytest.mark.parametrize("name,result", [
    ("get_quotes", {"quotes": {"NBIS": {"last": "94"}}}),  # a price that is not a number
    ("get_option_candidates", {"state": "ok", "candidates": [{"expiry": "not a date", "strike": 95, "type": "call"}]}),
    ("get_group_comparison", {"recent_15m": "broken"}),
    ("get_market_regime", {"radar": {"state": "off"}, "vix": {"state": "unavailable"}}),
    ("get_breadth", {"state": "unavailable", "reason": "no list"}),
    ("get_symbol_news", None),
    ("get_trade_review", ["not", "a", "dict"]),
    ("get_peer_moves", {"peers": [{"symbol": "X", "change_pct": None}]}),
])
def test_malformed_or_empty_results_give_none(name, result):
    assert summarize(name, result) is None


def test_unknown_and_skipped_tools_give_none():
    assert summarize("get_nothing", {"state": "ok"}) is None
    assert summarize("propose_plan", {"proposal": {"kind": "watch"}}) is None
    assert summarize("get_positions", E.get_positions()) is None


def test_lines_are_capped_and_plain():
    quotes = {"fetched_at": "2026-10-23T15:12:00Z",
              "quotes": {f"SYM{i}‮\n": {"last": 123456.789 + i, "change_pct": -12.3456} for i in range(8)}}
    line = summarize("get_quotes", quotes)
    assert len(line) <= MAX_CHARS
    assert "‮" not in line and "\n" not in line
    long = {"state": "ok", "symbol": "X" * 200, "events": {"next_earnings": {"date": "2026-11-12"}}}
    capped = summarize("get_symbol_profile", long)
    assert len(capped) == MAX_CHARS and capped.endswith("…")


def test_fake_turn_carries_the_fact_on_completed_tool_events():
    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "Is NBIS's group confirming?"}], "NBIS", _cfg(),
                                                  copilot.FakeAdapter(delay_s=0), FixtureEvidence(), NOW)]
    events = asyncio.run(collect())
    done = {e["name"]: e for e in events if e["type"] == "tool" and e.get("status") == "ok" and e["name"] != "owner_context"}
    assert done["get_group_comparison"]["fact"] == "NBIS +0.84% vs SPY +0.09%, 4 of 6 peers up (15m, 11:12)"
    assert done["get_symbol_news"]["fact"] == "3 headlines since 08:10, latest 10:40"
    assert all("summary" in e for e in done.values())  # the evidence row's own line stays
    running = [e for e in events if e["type"] == "tool" and e.get("status") == "running"]
    assert running and all("fact" not in e for e in running)


def test_web_row_carries_the_fact():
    found = [{"type": "web_search_result", "url": f"https://example.com/{i}", "title": "t"} for i in range(3)]
    row = copilot.web_row("s1", "nbis news", found, NOW)
    assert row["fact"] == "Web: 3 results"
