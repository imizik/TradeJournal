"""The copilot's symbol profile and proof tools: live reads composed block by block from the Symbol page's caches and
the proof pages, each failing alone; replay unavailable; the fixture's NBIS scenario; the scripted model; allowlists."""
import json
from datetime import UTC, datetime

import pytest

from app.ai import copilot, copilot_profile, copilot_tools, research_job
from app.ai.copilot_fixture import FixtureEvidence
from tests.test_copilot import _text, _turn

NOW = datetime(2026, 10, 23, 15, 12, tzinfo=UTC)


def _overview_raw(symbol):
    meta = {"state": "ready", "source": "Tradier company fundamentals", "fetched_at": 1_792_000_000, "message": None}
    return {"symbol": symbol, "state": "ready", "datasets": {
        "company": {**meta, "name": "Nebius Group", "sector": "Technology", "employees": 1200, "ipo_date": "2025-10-21",
                    "description": "D" * 400, "ownership": {"as_of": "2026-06-30", "holders": 412, "percent_held": 41.3}},
        "ratios": {**meta, "pe": None, "price_to_sales": 38.2, "price_to_book": 6.1, "ev_to_ebitda": None, "dividend_yield": None, "beta_60_month": 2.4},
        "statistics": {**meta, "market_cap": 22.4e9, "enterprise_value": 21.1e9, "shares_outstanding": 237e6, "institutional_ownership": 41.3,
                       "average_volume_30_day": 18.5e6, "average_volume_90_day": 15e6}}}


def _events_raw(symbol, today):
    return {"symbol": symbol, "today": today.isoformat(), "time_zone": "America/New_York",
            "earnings": {"state": "ready", "fetched_at": 1_792_000_000, "message": None, "time_note": "n",
                         "next": {"date": "2026-11-12", "status": "estimated", "label": "Q3 2026"}, "reports": [{"date": "2026-08-07", "label": "Q2 2026"}]},
            "dividends": {"state": "ready", "next": {"ex_date": "2026-11-20", "amount": 0.1}, "last": None},
            "splits": {"state": "ready", "rows": [{"ex_date": "2025-06-10", "from": 1.0, "to": 10.0, "label": "10-for-1"}]}}


def _short_raw(symbol):
    return {"symbol": symbol, "as_of": "2026-10-23T15:00:00Z", "state": "ready",
            "interest": {"state": "ready", "source": "FINRA", "message": None, "settlement_date": "2026-10-15", "short_interest": 31_200_000,
                         "avg_daily_volume": 18e6, "days_to_cover": 1.7, "pct_of_shares_outstanding": 13.2, "settlement_note": "two weeks behind",
                         "previous": {"settlement_date": "2026-09-30", "short_interest": 28_800_000, "change_pct": 8.3}},
            "volume": {"state": "ready", "average_pct": 44.1, "note": "share of volume", "rows": [{"day": "x"}] * 20},
            "borrow": {"state": "ready", "hard_to_borrow": False, "note": "On the list.", "message": None}}


def _analysts_raw(symbol):
    ready = {"state": "ready", "source": "Yahoo", "provider": "yahoo", "fetched_at": 1_792_000_000, "message": None}
    return {"symbol": symbol, "state": "ready", "blocks": {
        "targets": {**ready, "value": {"mean": 118.0, "median": 120.0, "high": 150.0, "low": 85.0}},
        "ratings": {**ready, "note": "labels differ", "value": {"strong_buy": 6, "buy": 9, "hold": 3, "sell": 0, "strong_sell": 0}},
        "estimates": {**ready, "value": [{"period": "current quarter", "eps": {"avg": -0.31}, "revenue": {"avg": 185e6}}, {"period": "next quarter", "eps": {"avg": -0.2}}, {"period": "x"}]},
        "actions": {**ready, "value": [{"date": f"2026-10-{20 - i}", "firm": f"F{i}", "action": "raise", "to_grade": "Buy", "from_grade": "Hold", "target": 130.0, "prior_target": 100.0} for i in range(6)]},
        "history": {"state": "none", "source": "Yahoo", "message": None}}, "providers": {}}


# --------------------------------------------------------------------------- registration and allowlists

def test_the_tools_are_registered_validated_and_classed():
    assert {"get_symbol_profile", "get_proof"} <= copilot_tools.TOOL_NAMES
    assert copilot_tools.PROVENANCE["get_symbol_profile"][1] == "cached" and copilot_tools.PROVENANCE["get_proof"][1] == "saved"
    assert copilot_tools.validate("get_symbol_profile", {"symbol": "nbis"}) == {"symbol": "NBIS"}
    assert copilot_tools.validate("get_proof", {"scope": "week"}) == {"scope": "week"}
    assert copilot_tools.validate("get_proof", {"scope": "symbol", "symbol": "nbis"}) == {"scope": "symbol", "symbol": "NBIS"}
    for name, bad in (("get_symbol_profile", {}), ("get_proof", {}), ("get_proof", {"scope": "month"}), ("get_proof", {"scope": "symbol"}),
                      ("get_proof", {"scope": "week", "symbol": "NBIS"}), ("get_proof", {"scope": "week", "days": 7})):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_tools.validate(name, bad)
    # The profile is market data: research jobs get it. The proof is the owner's book: they never do, and "what changed" skips it.
    assert "get_symbol_profile" in research_job.JOB_TOOLS and "get_proof" not in research_job.JOB_TOOLS
    assert "get_proof" in copilot_tools.BOOK_CONTEXT_TOOLS and "get_proof" in copilot_tools.NOT_CURRENT_TOOLS
    assert "get_symbol_profile" not in copilot_tools.NOT_CURRENT_TOOLS


# --------------------------------------------------------------------------- the profile, live

def test_live_profile_composes_the_symbol_pages_caches_with_sources_and_ages(monkeypatch):
    from app.engine import symbol_info_analysts, symbol_info_short_feed, symbol_info_tradier
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "overview", _overview_raw)
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "events", _events_raw)
    monkeypatch.setattr(symbol_info_short_feed.short_feed, "view", _short_raw)
    monkeypatch.setattr(symbol_info_analysts.symbol_analysts, "view", _analysts_raw)
    out = copilot_tools.LiveEvidence().get_symbol_profile("NBIS")
    assert out["state"] == "ok" and out["symbol"] == "NBIS" and out["note"] == copilot_profile.PROFILE_NOTE
    assert out["company"]["sector"] == "Technology" and len(out["company"]["description"]) == copilot_profile.DESCRIPTION_CHARS
    assert out["company"]["fetched_at"] == "2026-10-14T17:46:40Z"  # the cache's own time, not now
    assert out["valuation"]["market_cap"] == 22.4e9 and out["valuation"]["price_to_sales"] == 38.2 and out["valuation"]["average_volume_30_day"] == 18.5e6
    assert out["ownership"] == {"state": "ready", "institutional_pct": 41.3, "holders_13f": 412, "as_of": "2026-06-30"}
    assert out["events"]["next_earnings"]["date"] == "2026-11-12" and out["events"]["last_report"]["label"] == "Q2 2026"
    assert out["events"]["dividends"]["next"]["ex_date"] == "2026-11-20" and out["events"]["splits"] == [{"ex_date": "2025-06-10", "label": "10-for-1"}]
    short = out["short"]["interest"]
    assert (short["pct_of_shares_outstanding"], short["days_to_cover"], short["change_pct_from_previous"], short["settlement_date"]) == (13.2, 1.7, 8.3, "2026-10-15")
    assert out["short"]["short_volume"] == {"state": "ready", "average_pct": 44.1, "note": "share of volume"}  # the twenty daily rows stay out
    assert out["short"]["borrow"]["hard_to_borrow"] is False
    assert out["analysts"]["targets"]["value"]["mean"] == 118.0 and out["analysts"]["targets"]["source"] == "Yahoo"
    assert out["analysts"]["ratings"]["note"] == "labels differ" and len(out["analysts"]["estimates"]["value"]) == 2
    assert len(out["analysts"]["recent_actions"]["value"]) == copilot_profile.MAX_ACTIONS and "prior_target" not in out["analysts"]["recent_actions"]["value"][0]
    assert out["analysts"]["last_reports"] == {"state": "none", "message": None}
    assert len(copilot_tools.bounded(out)) < copilot_tools.MAX_RESULT_CHARS
    assert copilot._summary("get_symbol_profile", out) == "next earnings 2026-11-12 · short 13.2% of shares · market cap 22.4B"


def test_live_profile_blocks_fail_alone(monkeypatch):
    from app.engine import symbol_info_analysts, symbol_info_short_feed, symbol_info_tradier

    def boom(*args, **kwargs):
        raise RuntimeError("provider secret")

    monkeypatch.setattr(symbol_info_tradier.symbol_events, "overview", boom)
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "events", _events_raw)
    monkeypatch.setattr(symbol_info_short_feed.short_feed, "view", boom)
    monkeypatch.setattr(symbol_info_analysts.symbol_analysts, "view", lambda symbol: {"symbol": symbol, "state": "unavailable", "blocks": {}, "providers": {}})
    out = copilot_tools.LiveEvidence().get_symbol_profile("NBIS")
    assert out["state"] == "ok"  # the events block stands
    assert out["company"]["state"] == "unavailable" and "secret" not in json.dumps(out)
    assert out["short"] == {"state": "unavailable", "reason": "short interest could not be read right now."}
    assert out["analysts"]["targets"] == {"state": "none", "message": None} and out["events"]["next_earnings"]["date"] == "2026-11-12"
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "events", boom)
    monkeypatch.setattr(symbol_info_analysts.symbol_analysts, "view", boom)
    gone = copilot_tools.LiveEvidence().get_symbol_profile("NBIS")
    assert gone["state"] == "unavailable" and copilot._summary("get_symbol_profile", gone) == "unavailable: No part of NBIS's profile could be read right now."


def test_symbol_events_now_carry_the_next_dividend_and_splits():
    out = copilot_tools.compact_events(_events_raw("NBIS", NOW.date()))
    assert out["next_dividend"] == {"ex_date": "2026-11-20", "amount": 0.1} and out["splits"] == [{"ex_date": "2025-06-10", "label": "10-for-1"}]
    assert copilot_tools.compact_events({"symbol": "X", "earnings": {}})["splits"] == []


# --------------------------------------------------------------------------- the proof, live

def _habits_card():
    rate = lambda n, t, pct: {"n": n, "trades": t, "excluded": 0, "pct": pct, "pnl": -100.0}  # noqa: E731
    return {"go_live": "2026-10-21", "window": 30, "recent_trades": 9, "baseline_trades": 1528,
            "habits": [{"key": "green_to_red", "label": "Was up 10% and $50, then closed red", "recent": rate(1, 9, 0.111), "baseline": rate(228, 1528, 0.149)}],
            "verdict": {"verdict": "not_enough_data", "rule": "r", "sample": 9, "changes": {}, "reason": "9 of 30 trades closed since the alerts went live."},
            "alerts_total": 7, "responses": {"held": 4, "exited_within_15m": 2, "unmatched": 1},
            "feedback": {"total": 7, "responded": 3, "unanswered": 4, "counts": {"helped": 2, "didnt": 1}},
            "alerts": [{"id": "secret-alert-id", "trade_id": "secret-trade-id"}]}


def _plans_card():
    return {"go_live": "2026-10-13", "trades": 14, "caveat": "Selection-biased.",
            "groups": [{"key": "planned", "label": "Plan saved before the entry", "in_verdict": True, "trades": 6, "counted": 6, "excluded": 0,
                        "pnl": 412.0, "mean_return_pct": 9.8, "median_return_pct": 8.0, "win_rate": 0.67, "habits": {}}],
            "verdict": {"verdict": "not_enough_data", "rule": "r", "planned": 6, "unplanned": 8, "difference_pct": None, "se_pct": None, "days": None,
                        "caveat": "c", "reason": "6 planned and 8 unplanned of 10 each needed."}}


def test_live_proof_reads_the_four_proofs_and_each_fails_alone(monkeypatch):
    from app.engine import alert_scorecard, exit_habits, outcomes, plan_proof
    monkeypatch.setattr(exit_habits, "build", lambda db, go_live=None: _habits_card())
    monkeypatch.setattr(plan_proof, "build", lambda db, go_live=None: _plans_card())
    seen = {}

    def week(db, start, end):
        seen["week"] = (start, end)
        return {"state": "ok", "by_kind": {"position_alert": {"count": 5, "complete": 4, "held": 3, "median_d1_pct": -1.2, "actions": {"held": 3}, "alt_usd_total": -84.0}}}

    monkeypatch.setattr(outcomes, "week", week)
    monkeypatch.setattr(outcomes, "build", lambda db, kind=None, start=None, symbol=None: {"since": "2026-10-13", "summary": {"ping": {"count": 2}}, "rows": [{"id": "secret"}], "truncated": False, "note": "n"})
    monkeypatch.setattr(alert_scorecard, "scorecard", lambda db, now, days=30: {
        "window_days": days, "alerts": 7, "rows": [{"id": "secret-row"}], "truncated": False,
        "summary": {"holding": {"alerts": 4, "closed": 3, "better": 1, "worse": 2, "even": 0, "open": 1, "not_measured": 0, "vs_alert_usd": -140.0}}})
    out = copilot_profile.live_proof("week", None, NOW)
    assert out["state"] == "ok" and out["note"] == copilot_profile.PROOF_NOTE
    assert out["alerts"]["verdict"] == "not_enough_data" and out["alerts"]["habits"][0]["recent"] == "1 of 9" and out["alerts"]["habits"][0]["baseline_pct"] == 14.9
    assert out["alerts"]["alerts"] == {"sent": 7, "responses": {"held": 4, "exited_within_15m": 2, "unmatched": 1},
                                       "feedback": {"total": 7, "responded": 3, "unanswered": 4, "counts": {"helped": 2, "didnt": 1}}}
    assert out["plans"]["groups"][0] == {"group": "planned", "trades": 6, "pnl": 412.0, "mean_return_pct": 9.8, "win_rate": 0.67, "counted_in_verdict": True}
    assert out["outcomes"]["scope"] == "week of 2026-10-19" and out["outcomes"]["by_kind"]["position_alert"]["count"] == 5
    assert seen["week"][0].isoformat() == "2026-10-19T04:00:00" and (seen["week"][1] - seen["week"][0]).days == 7  # Monday 00:00 New York, as UTC
    assert out["scorecard"]["by_decision"]["holding"] == {"alerts": 4, "closed": 3, "better": 1, "worse": 2, "even": 0, "open": 1, "vs_alert_usd": -140.0}
    assert "secret" not in json.dumps(out)  # no alert, trade or row ids leave
    assert len(copilot_tools.bounded(out)) < copilot_tools.MAX_RESULT_CHARS
    assert copilot._summary("get_proof", out) == "alerts not_enough_data · plans not_enough_data · 7 alerts scored"
    by_symbol = copilot_profile.live_proof("symbol", "NBIS", NOW)
    assert by_symbol["outcomes"] == {"scope": "NBIS since 2026-10-13", "state": "ok", "by_kind": {"ping": {"count": 2}}, "note": "n"}

    def boom(*args, **kwargs):
        raise RuntimeError("db secret")

    monkeypatch.setattr(exit_habits, "build", boom)
    monkeypatch.setattr(outcomes, "week", boom)
    partial = copilot_profile.live_proof("week", None, NOW)
    assert partial["state"] == "ok" and partial["alerts"] == {"state": "unavailable", "reason": "exit habits could not be read right now."}
    assert partial["outcomes"]["state"] == "unavailable" and partial["plans"]["state"] == "ok" and "secret" not in json.dumps(partial)
    monkeypatch.setattr(plan_proof, "build", boom)
    monkeypatch.setattr(alert_scorecard, "scorecard", boom)
    assert copilot_profile.live_proof("week", None, NOW)["state"] == "unavailable"


# --------------------------------------------------------------------------- replay, fixture, the scripted model

def test_replay_says_both_are_unavailable(tmp_path, monkeypatch):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from tests.test_copilot import _replay_store
    replay = ReplayEvidence(str(_replay_store(tmp_path / "r.sqlite", with_future=False)), parse_at("2026-10-23T11:12"))
    profile, proof = replay.get_symbol_profile("NBIS"), replay.get_proof("week")
    assert profile["state"] == "unavailable" and "get_symbol_events" in profile["reason"] and profile["as_of"] == "2026-10-23T11:12-04:00"
    assert proof["state"] == "unavailable" and "hindsight" in proof["reason"]


def test_fixture_serves_the_nbis_scenario():
    fixture = FixtureEvidence()
    profile = fixture.get_symbol_profile("NBIS")
    assert profile["state"] == "ok" and profile["events"]["next_earnings"]["date"] == "2026-11-12" == fixture.get_symbol_events("NBIS")["next_earnings"]["date"]
    assert profile["short"]["interest"]["pct_of_shares_outstanding"] == 13.2 and profile["analysts"]["targets"]["value"]["mean"] == 118.0
    assert fixture.get_symbol_profile("TSLA")["state"] == "unavailable"
    proof = fixture.get_proof("week")
    assert proof["alerts"]["verdict"] == "not_enough_data" and proof["plans"]["groups"][1]["group"] == "unplanned"
    assert fixture.get_proof("symbol", "NBIS")["outcomes"]["scope"] == "NBIS since 2026-10-13"
    for data in (profile, proof):
        assert len(copilot_tools.bounded(data)) < copilot_tools.MAX_RESULT_CHARS


def test_the_scripted_model_reads_the_profile_and_the_proof():
    events = _turn([{"role": "user", "content": "What is the catalyst for NBIS, and what does short interest look like?"}], copilot.FakeAdapter(0))
    names = {e["name"] for e in events if e["type"] == "tool" and e["status"] == "ok"}
    assert {"get_symbol_profile", "get_symbol_events"} <= names
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_symbol_profile" and e["status"] == "ok"]
    assert tool["provenance"]["kind"] == "simulated" and tool["summary"] == "next earnings 2026-11-12 · short 13.2% of shares · market cap 22.4B"
    text = _text(events)
    assert text.startswith("Verdict: Focus — NBIS: the next report is the dated catalyst.")
    assert "- Next earnings 2026-11-12 (estimated; Tradier calendar, fetched 2026-10-23T15:12:00Z)." in text
    assert "- Short interest 13.2% of shares, 1.7 days to cover, settled 2026-10-15 (FINRA, about two weeks behind)." in text

    events = _turn([{"role": "user", "content": "Are the alerts helping me yet?"}], copilot.FakeAdapter(0))
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_proof" and e["status"] == "ok"]
    assert tool["input"] == {"scope": "week"} and tool["summary"] == "alerts not_enough_data · plans not_enough_data · 7 alerts scored"
    text = _text(events)
    assert text.startswith("Verdict: Unclear — The proof pages as they stand; the samples decide, not me.")
    assert "- Alerts: not_enough_data (9 of 30 trades closed since the alerts went live.) over 9 trades since 2026-10-21; 7 sent, feedback on 3." in text
    assert "after Holding, 1 better and 2 worse than selling at the alert (-140 $)." in text
    assert "Against: every verdict here is a count under a fixed rule, not causation." in text

    events = _turn([{"role": "user", "content": "Is the proof for NBIS helping?"}], copilot.FakeAdapter(0))
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_proof" and e["status"] == "ok"]
    assert tool["input"] == {"scope": "symbol", "symbol": "NBIS"}


def test_the_prompt_tells_the_model_when_to_read_them():
    assert "read get_symbol_profile and name the source" in copilot.SYSTEM_PROMPT
    assert "read get_proof (scope week, or symbol for one name)" in copilot.SYSTEM_PROMPT
    assert "never turn a count into a judgement of them" in copilot.SYSTEM_PROMPT
