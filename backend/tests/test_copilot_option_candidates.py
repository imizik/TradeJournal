"""Option candidates (docs/copilot-lab.md § Option candidates): real contracts from the existing chain code for the
instrument question. Expiries bracket the horizon, strikes run from about 5% in the money to 10% out on the view's side,
the per-contract, spread, distance and break-even arithmetic is exact, a budget counts contracts at the ask, delta and
IV stay unavailable, the answer is capped and bounded, an unavailable provider says so; validated, routed and labelled,
simulated in the fixture, unavailable in replay, never given to research jobs; the scripted model compares contracts and
the plan card gets a pick list; the system prompt asks for trade-offs, never advice."""
import asyncio
import json
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.ai import copilot, copilot_options, copilot_tools, research_job
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.engine.chart_math import ET
from app.engine.options_chain import OptionsChainError
from app.engine.options_feed import OptionsFeed
from app.engine.options_models import OptionChain, OptionContract

TODAY = date(2026, 10, 23)
AT = datetime(2026, 10, 23, 15, 12, tzinfo=UTC)
SPOT = 100.0


def contract(expiry, kind, strike, bid=1.0, ask=1.2, root="NBIS", multiplier=100, oi=500, volume=40):
    return OptionContract(symbol=f"{root}{expiry:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}", underlying="NBIS", root=root,
                          expiration=expiry, option_type=kind, strike=strike, multiplier=multiplier, bid=bid, ask=ask, last=None,
                          bid_size=None, ask_size=None, volume=volume, open_interest=oi, bid_time=None, ask_time=None, trade_time=None,
                          iv=0.6, iv_smoothed=0.6, delta=0.5, gamma=0.01, theta=-0.1, vega=0.1, greeks_updated_at="2026-10-23 10:00:00")


def chain(expiry, strikes=range(80, 121), **kw):
    rows = [contract(expiry, kind, float(k), **kw) for k in strikes for kind in ("call", "put")]
    return OptionChain("NBIS", expiry, "tradier", AT, tuple(rows))


LISTED = [TODAY + timedelta(days=n) for n in (0, 7, 14, 21, 28, 56, 84)]


# --------------------------------------------------------------------------- which expiries

def test_expiries_bracket_the_horizon_with_the_first_at_or_after_it():
    pick = copilot_options.pick_expirations
    assert pick(LISTED, TODAY, 18) == [LISTED[2], LISTED[3], LISTED[4]]  # before (14 d), first at or after (21 d), after (28 d)
    assert pick(LISTED, TODAY, 21) == [LISTED[2], LISTED[3], LISTED[4]]  # an expiry on the horizon date reaches it
    assert pick(LISTED, TODAY, 60) == [LISTED[5], LISTED[6]]             # nothing listed after the one that reaches it
    assert pick(LISTED[1:], TODAY, 3) == [LISTED[1], LISTED[2]]          # nothing listed before the horizon
    assert pick(LISTED, TODAY, 365) == [LISTED[5], LISTED[6]]            # nothing reaches it: the longest two listed
    assert pick([], TODAY, 10) == []


def test_roles_and_reaching_the_horizon_are_said():
    chosen = copilot_options.pick_expirations(LISTED, TODAY, 18)
    out = copilot_options.candidates("NBIS", chosen, {d: chain(d) for d in chosen}, SPOT, TODAY, 18, "long", as_of="t")
    assert [(e["days"], e["role"], e["weekday"]) for e in out["expiries"]] == [(14, "before", "Fri"), (21, "first_at_or_after", "Fri"),
                                                                              (28, "after", "Fri")]
    assert out["reaches_horizon"] is True and "horizon_note" not in out and out["horizon_date"] == "2026-11-10"
    far = copilot_options.pick_expirations(LISTED, TODAY, 365)
    out = copilot_options.candidates("NBIS", far, {d: chain(d) for d in far}, SPOT, TODAY, 365, "long")
    assert out["reaches_horizon"] is False and "longest listed" in out["horizon_note"]


# --------------------------------------------------------------------------- which strikes

def test_calls_run_from_5pct_in_the_money_to_10pct_out_and_puts_mirror_it():
    chosen = copilot_options.pick_expirations(LISTED, TODAY, 18)
    chains = {d: chain(d) for d in chosen}
    calls = copilot_options.candidates("NBIS", chosen, chains, SPOT, TODAY, 18, "long")
    assert {r["type"] for r in calls["candidates"]} == {"call"} and calls["side"] == "calls"
    assert all(95 <= r["strike"] <= 110 for r in calls["candidates"])
    puts = copilot_options.candidates("NBIS", chosen, chains, SPOT, TODAY, 18, "short")
    assert {r["type"] for r in puts["candidates"]} == {"put"} and puts["side"] == "puts"
    assert all(90 <= r["strike"] <= 105 for r in puts["candidates"])
    # The first expiry at or after the horizon gets the most: 3 / 3 / 2 of the 8. Each starts at the money and spreads
    # to the window's ends.
    per = {e["role"]: [r["strike"] for r in calls["candidates"] if r["expiry"] == e["expiry"]] for e in calls["expiries"]}
    assert per == {"first_at_or_after": [95.0, 100.0, 110.0], "after": [95.0, 100.0, 110.0], "before": [100.0, 110.0]}
    assert len(calls["candidates"]) == copilot_options.MAX_CANDIDATES
    assert [r["strike"] for r in puts["candidates"] if r["days"] == 21] == [90.0, 100.0, 105.0]


def test_two_expiries_split_the_eight_and_other_roots_or_unquoted_contracts_are_left_out():
    first, second = LISTED[3], LISTED[4]
    adjusted = contract(first, "call", 102.5, root="NBIS1")  # an adjusted contract after a corporate action is another root
    one_sided = contract(first, "call", 101.0, bid=None)
    crossed = contract(first, "call", 103.0, bid=2.0, ask=1.5)
    stub = OptionChain("NBIS", first, "tradier", AT, chain(first, strikes=range(95, 111, 5)).contracts + (adjusted, one_sided, crossed))
    out = copilot_options.candidates("NBIS", [first, second], {first: stub, second: chain(second)}, SPOT, TODAY, 21, "long")
    strikes = [r["strike"] for r in out["candidates"] if r["expiry"] == first.isoformat()]
    assert strikes == [95.0, 100.0, 105.0, 110.0] and len(out["candidates"]) == 8  # 4 and 4
    assert out["skipped_without_quote"] == 2  # the one-sided and the crossed quote; NBIS1 is not counted at all


# --------------------------------------------------------------------------- the arithmetic

def test_per_contract_spread_distance_break_even_and_budget():
    expiry = LISTED[3]
    stub = OptionChain("NBIS", expiry, "tradier", AT, (contract(expiry, "call", 105.0, bid=2.40, ask=2.60, oi=1200, volume=85),
                                                       contract(expiry, "put", 95.0, bid=1.90, ask=2.10, oi=None, volume=None)))
    [call] = copilot_options.candidates("NBIS", [expiry], {expiry: stub}, SPOT, TODAY, 21, "long", budget_usd=1000)["candidates"]
    assert call == {"expiry": "2026-11-13", "days": 21, "type": "call", "strike": 105.0, "bid": 2.4, "ask": 2.6, "mid": 2.5,
                    "per_contract": {"bid": 240.0, "ask": 260.0, "mid": 250.0}, "spread_pct": 8.0, "open_interest": 1200, "volume": 85,
                    "delta": "unavailable", "iv": "unavailable",  # the chain carries provider greeks; they are not passed on
                    "to_strike_pct": 5.0, "breakeven_move_pct": 7.6,  # 105 + 2.60 = 107.60, +7.6% from 100
                    "budget_buys": {"contracts": 3, "cost_usd": 780.0}}
    [put] = copilot_options.candidates("NBIS", [expiry], {expiry: stub}, SPOT, TODAY, 21, "short", budget_usd=210)["candidates"]
    assert put["breakeven_move_pct"] == -7.1 and put["to_strike_pct"] == -5.0  # 95 - 2.10 = 92.90
    assert "open_interest" not in put and "volume" not in put  # not listed, so not shown
    assert put["budget_buys"] == {"contracts": 1, "cost_usd": 210.0}  # exactly one at the ask
    unknown = OptionChain("NBIS", expiry, "tradier", AT, (contract(expiry, "call", 100.0, multiplier=None),))
    [row] = copilot_options.candidates("NBIS", [expiry], {expiry: unknown}, SPOT, TODAY, 21, "long", budget_usd=500)["candidates"]
    assert row["per_contract"] == "unavailable" and row["budget_buys"] == "unavailable"  # no multiplier is no licence to assume 100
    assert "budget_buys" not in copilot_options.candidates("NBIS", [expiry], {expiry: stub}, SPOT, TODAY, 21, "long")["candidates"][0]


def test_the_answer_is_capped_and_cut_by_rows_never_mid_json(monkeypatch):
    chosen = copilot_options.pick_expirations(LISTED, TODAY, 18)
    dense = {d: chain(d, strikes=[80 + 0.5 * i for i in range(100)]) for d in chosen}
    out = copilot_options.candidates("NBIS", chosen, dense, SPOT, TODAY, 18, "long", budget_usd=5000, as_of="2026-10-23T15:12:00Z")
    assert len(out["candidates"]) == 8
    marked = {**copilot.SIMULATED_MARKER, **out}
    assert len(json.dumps(marked, separators=(",", ":"))) <= copilot_tools.MAX_RESULT_CHARS  # with the fixture's marker too
    monkeypatch.setattr(copilot_tools, "MAX_RESULT_CHARS", 2500)
    small = copilot_options.candidates("NBIS", chosen, dense, SPOT, TODAY, 18, "long", budget_usd=5000)
    assert 0 < len(small["candidates"]) < 8 and small["trimmed"] == 8 - len(small["candidates"])
    assert len(json.dumps(small, separators=(",", ":"))) <= 2500


def test_missing_chains_are_partial_and_an_empty_window_says_why():
    chosen = copilot_options.pick_expirations(LISTED, TODAY, 18)
    out = copilot_options.candidates("NBIS", chosen, {chosen[1]: chain(chosen[1])}, SPOT, TODAY, 18, "long", issue="pacing")
    assert out["state"] == "partial" and out["reason"] == "pacing" and len(out["candidates"]) == 8  # the present one takes all 8
    assert [e.get("missing", False) for e in out["expiries"]] == [True, False, True]
    none = copilot_options.candidates("NBIS", chosen, {}, SPOT, TODAY, 18, "long", issue="Tradier refused option data.")
    assert none["state"] == "unavailable" and none["candidates"] == [] and none["reason"] == "Tradier refused option data."
    far = copilot_options.candidates("NBIS", chosen, {d: chain(d, strikes=[50, 200]) for d in chosen}, SPOT, TODAY, 18, "long")
    assert far["state"] == "none" and "No call in the strike window" in far["reason"]


# --------------------------------------------------------------------------- the live read

class Client:
    """A stand-in for the Tradier adapter: today's listed expirations and a chain each, counting requests."""

    def __init__(self, error=None):
        self.error, self.calls = error, []
        self.today = datetime.now(ET).date()

    def expirations(self, symbol, wait=False):
        self.calls.append(("expirations", symbol))
        if self.error:
            raise self.error
        return [self.today + timedelta(days=n) for n in (7, 14, 21, 28, 56)]

    def chain(self, symbol, expiration, wait=False):
        self.calls.append(("chain", expiration))
        return chain(expiration)


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


@pytest.fixture
def live(monkeypatch):
    from app.engine import options_feed as feed_module, quotes
    client = Client()
    monkeypatch.setattr(feed_module, "options_feed", OptionsFeed(client=client, calendar=Calendar()))
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: SPOT for s in symbols})
    return client


def test_the_live_read_is_one_cached_pass_with_the_chains_as_of(live):
    out = copilot_tools.call(copilot_tools.LiveEvidence(), "get_option_candidates",
                             copilot_tools.validate("get_option_candidates", {"symbol": "NBIS", "horizon_days": 18, "direction": "long"}))
    assert out["state"] == "ok" and len(out["candidates"]) == 8 and out["spot"] == SPOT
    assert [e["days"] for e in out["expiries"]] == [14, 21, 28]
    assert live.calls == [("expirations", "NBIS")] + [("chain", live.today + timedelta(days=n)) for n in (14, 21, 28)]
    read_at = datetime.fromisoformat(out["as_of"].replace("Z", "+00:00"))  # when the feed read the chains
    assert abs((datetime.now(timezone.utc) - read_at).total_seconds()) < 60
    prov = copilot_tools.provenance("get_option_candidates", out, "live")
    assert prov["kind"] == "fetched" and "Tradier option chains" in prov["source"] and prov["as_of"] == out["as_of"]
    again = copilot_options.live_candidates("NBIS", 18, "long")
    assert again["candidates"] == out["candidates"] and len(live.calls) == 4  # served from the feed's cache: no new reads


def test_an_unavailable_provider_or_price_says_so(live, monkeypatch):
    from app.engine import options_feed as feed_module, quotes
    down = Client(OptionsChainError("Set TRADIER_API_KEY on the private backend to read option chains.", "not_configured"))
    monkeypatch.setattr(feed_module, "options_feed", OptionsFeed(client=down, calendar=Calendar()))
    out = copilot_options.live_candidates("NBIS", 18, "long")
    assert out == {"symbol": "NBIS", "direction": "long", "horizon_days": 18, "candidates": [], "state": "unavailable",
                   "reason": "Set TRADIER_API_KEY on the private backend to read option chains."}
    assert copilot._summary("get_option_candidates", out) == "unavailable: Set TRADIER_API_KEY on the private backend to read option chains."
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: None for s in symbols})
    assert copilot_options.live_candidates("NBIS", 18, "long")["reason"] == "No current NBIS price, so strikes cannot be placed."


# --------------------------------------------------------------------------- the tool

def test_the_tool_is_validated_routed_labelled_and_never_a_job_tool(monkeypatch):
    v = copilot_tools.validate
    assert v("get_option_candidates", {"symbol": "nbis", "horizon_days": 21, "direction": "long"}) == \
        {"symbol": "NBIS", "horizon_days": 21, "direction": "long"}
    assert v("get_option_candidates", {"symbol": "NBIS", "horizon_days": 365, "direction": "short", "budget_usd": 1500}) == \
        {"symbol": "NBIS", "horizon_days": 365, "direction": "short", "budget_usd": 1500.0}
    assert v("get_option_candidates", {"symbol": "NBIS", "horizon_days": 1, "direction": "long", "budget_usd": 1_000_000})["budget_usd"] == 1_000_000
    for bad in ({"symbol": "NBIS", "direction": "long"}, {"symbol": "NBIS", "horizon_days": 0, "direction": "long"},
                {"symbol": "NBIS", "horizon_days": 366, "direction": "long"}, {"symbol": "NBIS", "horizon_days": 7.5, "direction": "long"},
                {"symbol": "NBIS", "horizon_days": True, "direction": "long"}, {"symbol": "NBIS", "horizon_days": 7, "direction": "up"},
                {"symbol": "NBIS", "horizon_days": 7}, {"symbol": "nb is", "horizon_days": 7, "direction": "long"},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "budget_usd": 0},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "budget_usd": -5},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "budget_usd": float("inf")},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "budget_usd": float("nan")},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "budget_usd": 1_000_001},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "budget_usd": True},
                {"symbol": "NBIS", "horizon_days": 7, "direction": "long", "strike": 100}):
        with pytest.raises(copilot_tools.ToolInputError):
            v("get_option_candidates", bad)
    seen = []
    monkeypatch.setattr(copilot_options, "live_candidates", lambda *a: seen.append(a) or {"state": "ok"})
    copilot_tools.call(copilot_tools.LiveEvidence(), "get_option_candidates",
                       v("get_option_candidates", {"symbol": "NBIS", "horizon_days": 21, "direction": "long", "budget_usd": 900}))
    assert seen == [("NBIS", 21, "long", 900.0)]
    assert "get_option_candidates" not in research_job.JOB_TOOLS and "mcp__tradejournal__get_option_candidates" not in research_job.LAB_TOOLS
    assert "get_option_candidates" not in copilot_tools.BOOK_CONTEXT_TOOLS  # market data, so "what changed" keeps it


def test_replay_is_unavailable_and_the_fixture_is_a_simulated_nbis_chain():
    replay = ReplayEvidence.__new__(ReplayEvidence)
    assert replay.get_option_candidates("NBIS", 21, "long")["state"] == "unavailable"
    fixture = FixtureEvidence().get_option_candidates("NBIS", 21, "long", 1500.0)
    assert fixture["simulated"] is True and fixture["state"] == "ok" and fixture["spot"] == 94.35
    assert [e["expiry"] for e in fixture["expiries"]] == ["2026-11-06", "2026-11-13", "2026-11-20"]
    assert len(fixture["candidates"]) == 8 and all(r["delta"] == r["iv"] == "unavailable" for r in fixture["candidates"])
    assert len(copilot_tools.bounded({**copilot.SIMULATED_MARKER, **fixture})) <= copilot_tools.MAX_RESULT_CHARS
    assert copilot_tools.provenance("get_option_candidates", fixture, "fixture")["kind"] == "simulated"
    assert FixtureEvidence().get_option_candidates("CRWV", 21, "long")["state"] == "unavailable"


# --------------------------------------------------------------------------- the scripted model, the card, the prompt

def test_the_scripted_model_compares_contracts_and_the_card_gets_a_pick_list():
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False, key_configured=False)

    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "Which strike and expiry for NBIS calls over 3 weeks?"}],
                                                  "NBIS", cfg, copilot.FakeAdapter(0), FixtureEvidence(), datetime(2026, 10, 23, 11, 12))]
    events = asyncio.run(collect())
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_option_candidates" and e["status"] == "ok"]
    assert tool["input"] == {"symbol": "NBIS", "horizon_days": 21, "direction": "long"}
    assert tool["provenance"]["kind"] == "simulated" and tool["summary"] == "8 calls across 3 expiries for a 21-day horizon"
    picks = tool["candidates"]
    assert picks["symbol"] == "NBIS" and picks["simulated"] is True and len(picks["picks"]) == 8
    assert picks["picks"][0] == {"label": "Nov 6 '26 95C", "days": 14, "ask_contract": 565.0, "ask": 5.65, "delta": None}
    assert picks["as_of"] == tool["provenance"]["as_of"]  # the premium's read time, for "Size it for me"
    assert all(len(p["label"]) <= 40 for p in picks["picks"])  # fits the plan's contract hint
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "2026-11-06 (14 d) 95 call: $5.65 ask ($565 a contract), spread 4.0%, needs +6.7% by expiry to break even; " \
           "expires before your horizon: a mismatch to name." in text
    assert "2026-11-13 (21 d) 95 call" in text and "covers the horizon" in text and "runs past the horizon" in text
    assert "not a recommendation" in text and "haven't estimated them" in text
    assert copilot.option_candidates_card({"state": "unavailable"}) is None


def test_the_prompt_asks_for_candidates_as_trade_offs_never_advice():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    for phrase in ("When the owner names an option or a horizon, or before you propose a trade_plan on options, call get_option_candidates",
                   "compare 2-3 of its contracts against the horizon",
                   "a thesis in weeks through a contract that expires in days is a mismatch to name",
                   "Premium, spread and break-even move are the numbers to quote",
                   "Never recommend a specific contract as advice: present the trade-offs and let them choose"):
        assert phrase in prompt, phrase
    # The pinned instrument sentences stay: no IV or Greeks, so they are never estimated.
    for phrase in ("3. Instrument", "no implied volatility or Greeks", "a mismatch worth naming, not a bad thesis",
                   "exactly one propose_plan kind=trade_plan", "Before you propose a trade_plan, call get_level_history"):
        assert phrase in prompt, phrase
