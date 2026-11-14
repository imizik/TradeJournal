"""The desk ticket's two-leg vertical spreads (engine/desk_ticket.py § a two-leg vertical spread): the money math for
every case (debit and credit, calls and puts, the ×100 multiplier and the count), the plan words that name a vertical
and the ones that stay refused, both legs' quotes from the ticket's one chain read, and the Play check on the spread as
a whole. Hand-checked numbers; copy only, nothing sends. No network."""

import dataclasses
from datetime import UTC, date, datetime

import pytest
from app.engine import day_journal, desk_ticket, play_check
from app.engine.chart_math import ET
from tests import test_desk_ticket as base
from tests.test_desk_ticket import NBIS, NOW, WED, chain_read, contract, plan, ticket
from tests.test_play_check import oc, chain as play_chain, fresh

DEC19 = date(2026, 12, 19)
engine, lab = base.engine, base.lab  # the ticket tests' fixtures: an in-memory journal and the routes


# --- the arithmetic: every case --------------------------------------------------------------------------------------

def test_a_call_debit_spread():
    # Buy the 100 call, sell the 110: a debit. 3.20 a share x 100 x 2 = $640 paid, all of it the most to lose; the most to
    # make is the 6.80 left of the 10 width, x 200 = $1,360. Break-even at expiry: 100 + 3.20.
    f = desk_ticket.spread_figures("call", 100, 110, 3.20, 2, 100, 95.0, 8.0)
    assert f["type"] == "debit" and f["width"] == 10
    assert (f["cost"], f["credit"], f["max_loss"], f["max_gain"]) == (640.0, None, 640.0, 1360.0)
    assert f["breakeven"] == 103.2
    assert f["move_pct"] == 8.63 and f["vs_expected"] == 1.1  # (103.2 - 95) / 95 = 8.63%, against an 8% expected move
    assert f["warning"] is None


def test_a_call_credit_spread():
    # Sell the 100 call, buy the 110: a credit. 3.20 taken in x 100 = $320, the most to make; the most to lose is the
    # width less the credit, 6.80 x 100 = $680. Break-even: the lower strike plus the credit, 103.20.
    f = desk_ticket.spread_figures("call", 110, 100, 3.20, 1, 100, 95.0)
    assert f["type"] == "credit" and f["width"] == 10
    assert (f["cost"], f["credit"], f["max_loss"], f["max_gain"]) == (None, 320.0, 680.0, 320.0)
    assert f["breakeven"] == 103.2


def test_a_put_debit_spread():
    # Buy the 100 put, sell the 90: a debit. 4.00 x 100 x 3 = $1,200 paid; most to make 6.00 x 300 = $1,800.
    # Break-even: the higher strike less the debit, 96.
    f = desk_ticket.spread_figures("put", 100, 90, 4.00, 3, 100, 98.0)
    assert f["type"] == "debit"
    assert (f["cost"], f["credit"], f["max_loss"], f["max_gain"]) == (1200.0, None, 1200.0, 1800.0)
    assert f["breakeven"] == 96.0 and f["move_pct"] == round((96 - 98) / 98 * 100, 2)


def test_a_put_credit_spread():
    # Sell the 100 put, buy the 90: a credit. 2.50 x 100 = $250 taken in; most to lose 7.50 x 100 = $750.
    # Break-even: the higher strike less the credit, 97.50.
    f = desk_ticket.spread_figures("put", 90, 100, 2.50, 1, 100, 101.0)
    assert f["type"] == "credit"
    assert (f["cost"], f["credit"], f["max_loss"], f["max_gain"]) == (None, 250.0, 750.0, 250.0)
    assert f["breakeven"] == 97.5


def test_the_dollars_scale_with_the_multiplier_and_the_count_and_half_strikes_stay_exact():
    one = desk_ticket.spread_figures("call", 102.5, 107.5, 1.85, 1, 100, None)
    assert (one["cost"], one["max_gain"], one["breakeven"], one["width"]) == (185.0, 315.0, 104.35, 5.0)
    ten = desk_ticket.spread_figures("call", 102.5, 107.5, 1.85, 10, 100, None)
    assert (ten["cost"], ten["max_gain"]) == (1850.0, 3150.0)
    # An adjusted contract's multiplier (here 10 shares) is used as given, never assumed to be 100.
    small = desk_ticket.spread_figures("call", 102.5, 107.5, 1.85, 1, 10, None)
    assert (small["cost"], small["max_gain"]) == (18.5, 31.5)
    # No count: no dollars, but the per-share break-even still stands; no stock price: no move.
    bare = desk_ticket.spread_figures("put", 90, 100, 2.50, None, 100, None)
    assert (bare["cost"], bare["credit"], bare["max_loss"], bare["max_gain"]) == (None, None, None, None)
    assert bare["breakeven"] == 97.5 and bare["move_pct"] is None


@pytest.mark.parametrize("kind,long_strike,short_strike,limit", [
    ("call", 100, 110, 10.0), ("call", 100, 110, 12.0), ("call", 110, 100, 10.0), ("put", 100, 90, 10.5), ("put", 90, 100, 10.0)])
def test_a_limit_at_or_over_the_width_gives_no_figures_and_says_why(kind, long_strike, short_strike, limit):
    f = desk_ticket.spread_figures(kind, long_strike, short_strike, limit, 1, 100, 95.0)
    assert f["warning"] and "width" in f["warning"]
    assert (f["cost"], f["credit"], f["max_loss"], f["max_gain"], f["breakeven"]) == (None, None, None, None, None)


@pytest.mark.parametrize("limit", [None, 0, -1.0])
def test_no_limit_gives_nothing_but_the_shape(limit):
    f = desk_ticket.spread_figures("call", 100, 110, limit, 1, 100, 95.0)
    assert (f["type"], f["width"]) == ("debit", 10)
    assert f["cost"] is None and f["breakeven"] is None and f["warning"] is None


def test_worth_and_profit_at_the_plans_levels_at_expiry():
    # Debit 100/110 call at 3.20, 2 spreads. Target 112: worth the full 10 width, +$1,360 (the most it makes). Stop 90:
    # worth nothing, -$640 (all of it). Entry 105: worth 5, +(5 - 3.20) x 200 = +$360.
    f = desk_ticket.spread_figures("call", 100, 110, 3.20, 2, 100, 95.0, levels={"entry": 105.0, "target": 112.0, "stop": 90.0})
    at = {r["role"]: (r["worth"], r["pnl"]) for r in f["at_levels"]}
    assert at == {"entry": (5.0, 360.0), "target": (10.0, 1360.0), "stop": (0.0, -640.0)}
    # Credit 100/110 call at 3.20, 1 spread: at 90 it expires worthless, +$320 kept; at 112 buying it back costs the
    # 10 width, -$680 (the most it loses).
    c = desk_ticket.spread_figures("call", 110, 100, 3.20, 1, 100, 95.0, levels={"stop": 112.0, "target": 90.0, "entry": None})
    assert {r["role"]: (r["worth"], r["pnl"]) for r in c["at_levels"]} == {"stop": (10.0, -680.0), "target": (0.0, 320.0)}
    # Put debit 100/90 at 4.00, 3 spreads: at 85 the full 10, +$1,800; at 100 nothing, -$1,200.
    p = desk_ticket.spread_figures("put", 100, 90, 4.00, 3, 100, 98.0, levels={"target": 85.0, "stop": 100.0})
    assert {r["role"]: (r["worth"], r["pnl"]) for r in p["at_levels"]} == {"target": (10.0, 1800.0), "stop": (0.0, -1200.0)}
    # Put credit 100/90 at 2.50: at 85, -$750; at 101, +$250; at 98, worth 2, +$50.
    q = desk_ticket.spread_figures("put", 90, 100, 2.50, 1, 100, 101.0, levels={"stop": 85.0, "target": 101.0, "entry": 98.0})
    assert {r["role"]: (r["worth"], r["pnl"]) for r in q["at_levels"]} == {"stop": (10.0, -750.0), "target": (0.0, 250.0), "entry": (2.0, 50.0)}
    # No count: the worth, no dollars.
    n = desk_ticket.spread_figures("call", 100, 110, 3.20, None, 100, 95.0, levels={"target": 112.0})
    assert n["at_levels"] == [{"role": "target", "price": 112.0, "worth": 10.0, "pnl": None}]


def test_the_shape_of_each_spread():
    assert desk_ticket.is_debit("call", 100, 110) and not desk_ticket.is_debit("call", 110, 100)
    assert desk_ticket.is_debit("put", 100, 90) and not desk_ticket.is_debit("put", 90, 100)
    # Bull: a call debit and a put credit. Bear: a put debit and a call credit.
    assert desk_ticket.spread_bullish("call", 100, 110) and desk_ticket.spread_bullish("put", 90, 100)
    assert not desk_ticket.spread_bullish("put", 100, 90) and not desk_ticket.spread_bullish("call", 110, 100)
    assert desk_ticket.spread_value("call", 100, 110, 104) == 4 and desk_ticket.spread_value("call", 110, 100, 104) == -4
    assert desk_ticket.spread_value("put", 100, 90, 120) == 0 and desk_ticket.spread_value("put", 90, 100, 50) == -10
    assert desk_ticket.spread_label("NBIS", "call", 110, 100, DEC19) == "NBIS $100/$110 Call Credit Spread 12/19/26"
    assert desk_ticket.spread_label("NBIS", "put", 102.5, 97.5, DEC19) == "NBIS $97.5/$102.5 Put Debit Spread 12/19/26"


def test_spreads_for_a_risk_in_dollars():
    assert desk_ticket.spreads_for_risk(1000, "debit", 3.20, 10, 100) == 3  # $320 each
    assert desk_ticket.spreads_for_risk(1000, "credit", 3.20, 10, 100) == 1  # $680 each at risk
    assert desk_ticket.spreads_for_risk(500, "credit", 3.20, 10, 100) is None  # not one
    assert desk_ticket.spreads_for_risk(640, "debit", 3.20, 10, 100) == 2  # exactly two, not one by rounding
    assert desk_ticket.spreads_for_risk(1000, "debit", 10.0, 10, 100) is None  # a limit at the width risks nothing sane
    assert desk_ticket.spreads_for_risk(None, "debit", 3.20, 10, 100) is None


# --- the plan's words ------------------------------------------------------------------------------------------------

def _s(kind, expiry, long_strike, short_strike):
    return {"kind": kind, "expiry": expiry, "long": long_strike, "short": short_strike}


@pytest.mark.parametrize("words,expected", [
    ("NBIS 12/19 100/110C", _s("call", DEC19, 100.0, 110.0)),
    ("NBIS 100/110 call spread Dec 19", _s("call", DEC19, 100.0, 110.0)),
    ("$100/$110 Call Debit Spread 12/19/26", _s("call", DEC19, 100.0, 110.0)),
    ("NBIS 12/19/26 100/110C credit spread", _s("call", DEC19, 110.0, 100.0)),
    ("Dec 19 '26 95/90 put credit spread", _s("put", DEC19, 90.0, 95.0)),
    ("95P/90P Dec 19", _s("put", DEC19, 95.0, 90.0)),
    ("Nov 21 105-110 call spread", _s("call", date(2026, 11, 21), 105.0, 110.0)),
    ("102.5/107.5C 11/13", _s("call", date(2026, 11, 13), 102.5, 107.5)),
    ("Nov 21 105-110 calls", None),  # a dash without "spread" may be a range of single strikes
    ("NBIS Dec 19 100 straddle", None),
    ("100/110 strangle Dec 19", None),
    ("95/100/105/110 call condor Dec 19", None),
    ("100/110/120C butterfly Dec 19", None),
    ("100/110/120C Dec 19", None),  # three strikes, no word: not a vertical
    ("roll 100C to 110C Dec 19", None),
    ("100/110C Dec 19 / Jan 16 calendar", None),
    ("100/110C Dec 19 and Jan 16", None),  # two expiries
    ("100/110C, 120C Dec 19", None),  # a third leg
    ("NBIS 11/13 100C", None),  # one contract is not a spread
    ("100/110C", None),  # no expiry
    ("100/100C Dec 19", None),
    (None, None),
])
def test_a_vertical_is_read_only_when_stated_plainly(words, expected):
    assert desk_ticket.read_spread(words, WED) == expected


def test_single_contract_words_still_refuse_a_spread():
    assert desk_ticket.read_contract("NBIS 12/19 100/110C", WED) is None
    assert desk_ticket.read_contract("100/110 call spread Dec 19", WED) is None


# --- the ticket ------------------------------------------------------------------------------------------------------

CHAIN = (contract(100.0, bid=3.10, ask=3.30), contract(110.0, bid=0.97, ask=1.03))


def test_a_call_debit_spread_from_the_chain(engine):
    plan(engine, size="risk $500")
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, pick_kind="call", chain_read=chain_read(*CHAIN))
    s = found["spread"]
    assert found["state"] == "ok" and found["contract"] is None
    assert s["label"] == "NBIS $100/$110 Call Debit Spread 11/13/26" and s["type"] == "debit" and s["width"] == 10
    assert s["source"] == "picked" and s["multiplier"] == 100
    long_leg, short_leg = s["legs"]
    assert (long_leg["action"], long_leg["strike"], long_leg["quote"]["bid"], long_leg["quote"]["ask"], long_leg["quote"]["mid"]) == ("buy", 100.0, 3.1, 3.3, 3.2)
    assert (short_leg["action"], short_leg["strike"], short_leg["quote"]["mid"]) == ("sell", 110.0, 1.0)
    # Net at the mid: 3.20 - 1.00 = 2.20 paid. At the natural price: buy at the 3.30 ask, sell at the 0.97 bid = 2.33.
    assert (s["net_mid"], s["net_natural"]) == (2.2, 2.33)
    assert s["rough"] == [] and s["against_plan"] is None
    # The default limit is the net mid; "risk $500" buys two ($220 each); the figures follow.
    assert found["limit"] == 2.2 and found["contracts"] == 2
    f = found["figures"]
    assert (f["cost"], f["max_loss"], f["max_gain"], f["breakeven"]) == (440.0, 440.0, 1560.0, 102.2)
    # The plan's levels (entry 95.9, stop 90) at expiry: below the long strike both are worth nothing.
    assert {r["role"]: r["pnl"] for r in f["at_levels"]} == {"entry": -440.0, "stop": -440.0}


def test_a_call_credit_spread_from_the_chain_says_it_runs_against_a_long_plan(engine):
    plan(engine, size="2 contracts")
    found = ticket(engine, pick=(contract().expiration, 110.0), short_strike=100.0, pick_kind="call", chain_read=chain_read(*CHAIN))
    s = found["spread"]
    assert s["type"] == "credit" and s["label"] == "NBIS $100/$110 Call Credit Spread 11/13/26"
    assert (s["legs"][0]["action"], s["legs"][0]["strike"], s["legs"][1]["action"], s["legs"][1]["strike"]) == ("buy", 110.0, "sell", 100.0)
    # Taken in at the mid: 3.20 - 1.00 = 2.20. At the natural price: sell at the 3.10 bid, buy at the 1.03 ask = 2.07.
    assert (s["net_mid"], s["net_natural"]) == (2.2, 2.07)
    assert found["limit"] == 2.2 and found["contracts"] == 2
    f = found["figures"]
    assert (f["credit"], f["max_gain"], f["max_loss"], f["breakeven"]) == (440.0, 440.0, 1560.0, 102.2)
    assert s["bullish"] is False and s["against_plan"] == "This credit call spread gains as NBIS falls; your plan is long."


def test_a_put_spread_from_the_chain(engine):
    plan(engine, size="1 contract")
    puts = (contract(95.0, "put", bid=4.00, ask=4.20), contract(90.0, "put", bid=2.00, ask=2.10))
    found = ticket(engine, pick=(contract().expiration, 95.0), short_strike=90.0, pick_kind="put", chain_read=chain_read(*puts))
    s = found["spread"]
    # 4.10 - 2.05 = 2.05 paid at the mid; 4.20 - 2.00 = 2.20 at the natural price. 1 spread: $205, most made $295.
    assert s["type"] == "debit" and (s["net_mid"], s["net_natural"]) == (2.05, 2.2)
    f = found["figures"]
    assert (f["cost"], f["max_loss"], f["max_gain"], f["breakeven"]) == (205.0, 205.0, 295.0, 92.95)
    assert found["option_type"] == "put"


def test_a_spread_the_plan_names_in_its_words(engine):
    plan(engine, contract="NBIS 11/13 100/110C debit spread", size="1 contract")
    found = ticket(engine, chain_read=chain_read(*CHAIN))
    assert found["spread"]["source"] == "plan" and found["spread"]["label"] == "NBIS $100/$110 Call Debit Spread 11/13/26"
    assert found["plan_contract_words"] == "NBIS 11/13 100/110C debit spread"
    assert found["figures"]["cost"] == 220.0
    # A one-leg pick from the chain replaces it, on the plan's own side.
    single = ticket(engine, pick=(contract().expiration, 110.0), chain_read=chain_read(*CHAIN))
    assert single["spread"] is None and single["contract"]["label"] == "NBIS $110 Call 11/13/26"
    # So does a "spread" whose two strikes are the same strike.
    same = ticket(engine, pick=(contract().expiration, 110.0), short_strike=110.0, chain_read=chain_read(*CHAIN))
    assert same["spread"] is None and same["contract"]["strike"] == 110.0


def test_straddles_and_the_rest_keep_the_existing_message(engine):
    plan(engine, contract="NBIS 11/13 100 straddle")
    found = ticket(engine, chain_read=chain_read(*CHAIN), candidates_read=lambda *a: {"state": "missing", "reason": "none"})
    assert found["spread"] is None and found["contract"] is None and found["candidates"]["state"] == "missing"


def test_a_stale_leg_gives_no_net_price_and_says_so(engine):
    plan(engine, size="risk $500")
    stale = (contract(100.0, bid=3.10, ask=3.30), contract(110.0, bid=0.97, ask=1.03, quoted=NOW - 3600))
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*stale))
    s = found["spread"]
    assert s["legs"][1]["quote"]["state"] == "stale" and not {"bid", "ask", "mid"} & set(s["legs"][1]["quote"])
    assert s["legs"][1]["quote"]["as_of"] == NOW - 3600  # its time, shown with it
    assert (s["net_mid"], s["net_natural"], found["limit"]) == (None, None, None)
    assert found["contracts"] is None and found["figures"]["cost"] is None
    assert s["rough"] == ["the $110 leg has a stale quote"]
    assert found["check"]["overnight"]["state"] == "stale"


def test_a_missing_leg_and_a_wide_leg(engine):
    plan(engine)
    missing = ticket(engine, pick=(contract().expiration, 100.0), short_strike=115.0, chain_read=chain_read(*CHAIN))
    assert missing["spread"]["legs"][1]["quote"]["state"] == "missing" and missing["spread"]["net_mid"] is None
    assert missing["spread"]["rough"] == ["the $115 leg has no usable quote"]
    # A wide short leg (0.20 on a 1.00 mid, 20%): the net is shown, said to be rough.
    wide = (contract(100.0, bid=3.10, ask=3.30), contract(110.0, bid=0.90, ask=1.10))
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*wide))
    assert found["spread"]["net_mid"] == 2.2 and found["spread"]["legs"][1]["wide"] is True
    assert found["spread"]["rough"] == ["the $110 leg's market is wide (20% of its mid)"]


def test_crossed_quotes_and_mixed_multipliers_give_no_limit(engine):
    plan(engine)
    # The short leg priced over the long leg: a net "debit" below zero is no price to start from.
    crossed = (contract(100.0, bid=1.00, ask=1.10), contract(110.0, bid=1.20, ask=1.30))
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*crossed))
    assert found["spread"]["net_mid"] == -0.2 and found["limit"] is None
    assert "outside 0 to the 10 width" in found["spread"]["rough"][-1]
    mixed = (contract(100.0), contract(110.0, bid=0.97, ask=1.03, multiplier=10))
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*mixed))
    assert found["spread"]["multiplier"] is None and found["limit"] is None and found["figures"]["cost"] is None
    assert any("different multipliers" in r for r in found["spread"]["rough"])


# --- the Play check on a spread --------------------------------------------------------------------------------------

def test_the_play_check_says_habits_are_not_checked_and_a_hidden_ticker_stays_silent(engine, monkeypatch):
    plan(engine, size="1 contract")
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*CHAIN))
    habits = found["check"]["habits"]
    assert habits["state"] == "spread" and habits["fired"] == [] and "not checked" in habits["reason"]
    assert [line["part"] for line in found["check"]["play"]["lines"]] == ["stop", "target", "time", "size"]
    monkeypatch.setattr(day_journal, "quiet", lambda db: {"NBIS"})
    hidden = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*CHAIN))
    assert hidden["check"]["habits"]["state"] == "quiet" and hidden["check"]["habits"]["reason"] is None


NOW_ET = datetime(2026, 11, 13, 10, 0, tzinfo=ET)


def test_holding_a_debit_spread_overnight():
    # Long the 100 call (theta -0.10), short the 110 (theta -0.04): -0.06 a share net, $6 a day for one spread. Cost at
    # the mids 3.20 - 0.60 = 2.60, $260. Held to the expiry at an unchanged 95, both expire worthless: -$260.
    long_c, short_c = oc(100, mid=3.20, delta=0.40, theta=-0.10), oc(110, mid=0.60, delta=0.15, theta=-0.04)
    found = play_check.spread_overnight(symbol="NBIS", legs=(long_c, short_c), chain=play_chain(long_c, short_c), spot=95.0,
                                        now=NOW_ET, time_stop={"text": "x", "state": "pending",
                                                               "due_at": int(datetime(2026, 11, 23, 15, 0, tzinfo=ET).timestamp())},
                                        horizon=None, quote_for=fresh)
    assert found["basis"] == "per spread" and found["expires_first"] is True
    (row,) = found["rows"]
    assert row["label"] == "NBIS $100/$110 Call 11/20/26 spread" and row["unit"] == "spreads"
    assert (row["cost"], row["credit"], row["decay_day"], row["decay_pct"]) == (260.0, False, 6.0, 2.3)
    assert row["hold_cost"] == 260.0 and row["hold_cost_pct"] == 100.0
    assert row["breakeven"] == 102.6  # 100 + 2.60, at expiry


def test_holding_a_credit_spread_overnight_earns_the_decay():
    # Short the 100 call, long the 110: 2.60 taken in; time decay works for it, -$6 a day as a cost; held to expiry at
    # an unchanged 95 it keeps the $260 (a hold "cost" of -$260). Break-even 102.60.
    long_c, short_c = oc(110, mid=0.60, delta=0.15, theta=-0.04), oc(100, mid=3.20, delta=0.40, theta=-0.10)
    found = play_check.spread_overnight(symbol="NBIS", legs=(long_c, short_c), chain=play_chain(long_c, short_c), spot=95.0,
                                        now=NOW_ET, time_stop={"text": "x", "state": "pending",
                                                               "due_at": int(datetime(2026, 11, 23, 15, 0, tzinfo=ET).timestamp())},
                                        horizon=None, quote_for=fresh)
    (row,) = found["rows"]
    assert (row["cost"], row["credit"], row["decay_day"], row["decay_pct"]) == (260.0, True, -6.0, None)
    assert row["hold_cost"] == -260.0 and row["hold_cost_pct"] is None
    assert row["breakeven"] == 102.6


def test_a_spread_ticket_with_greeks_gets_its_overnight_block(engine):
    plan(engine, size="1 contract")
    at = NOW - 30
    legs = (dataclasses.replace(contract(100.0), iv=0.6, delta=0.45, theta=-0.10),
            dataclasses.replace(contract(110.0, bid=0.97, ask=1.03), iv=0.6, delta=0.15, theta=-0.04))
    assert legs[0].bid_time == datetime.fromtimestamp(at, UTC)
    found = ticket(engine, pick=(contract().expiration, 100.0), short_strike=110.0, chain_read=chain_read(*legs))
    night = found["check"]["overnight"]
    assert night["state"] == "ok" and night["basis"] == "per spread"
    assert night["rows"][0]["decay_day"] == 6.0 and night["rows"][0]["cost"] == 220.0


# --- the route -------------------------------------------------------------------------------------------------------

def test_the_route_takes_the_short_leg(engine, lab, monkeypatch):
    plan(engine)
    seen = {}

    def build(db, inv, **kw):
        seen.update(kw)
        return {"ok": True}
    monkeypatch.setattr(desk_ticket, "build", build)
    assert lab.get(f"/copilot/tickets/{NBIS}?expiration=2026-11-13&strike=100&short_strike=110&option_type=call").status_code == 200
    assert (seen["pick"], seen["short_strike"], seen["pick_kind"]) == ((date(2026, 11, 13), 100.0), 110.0, "call")
    # No pick: a short strike alone means nothing.
    assert lab.get(f"/copilot/tickets/{NBIS}?short_strike=110").status_code == 200
    assert (seen["pick"], seen["short_strike"], seen["pick_kind"]) == (None, None, None)
    assert lab.get(f"/copilot/tickets/{NBIS}?expiration=2026-11-13&strike=100&option_type=straddle").status_code == 422
