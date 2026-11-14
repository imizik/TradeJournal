"""The desk's roll ticket (engine/desk_roll.py, GET /copilot/roll): close a held long call or put and open another as one
copy-only order. The money math for every case (debit and credit rolls, calls and puts, x100 and the counts, a partial
roll, different counts as two orders, cost basis against the money in the trade after it, break-evens, days added), the
quotes' honesty (a stale or missing leg gives no net; a wide one a rough one), the refusals, and nothing sends. Hand-
checked numbers. No network."""

import dataclasses
from datetime import UTC, date, datetime
import inspect
from types import SimpleNamespace

import pytest
from app.engine import desk_roll
from app.routers import copilot_ticket as ticket_routes
from tests import test_desk_ticket as base
from tests.test_desk_ticket import NOW, REPO, contract

engine, lab = base.engine, base.lab  # the ticket tests' fixtures: an in-memory journal and the routes

NOV21, DEC19 = date(2026, 11, 21), date(2026, 12, 19)


def leg(strike, expiry, kind="call", bid=3.90, ask=4.10, quoted=NOW - 30, multiplier=100):
    found = contract(strike, kind, bid, ask, quoted, multiplier)
    return dataclasses.replace(found, expiration=expiry, symbol=f"NBIS{expiry:%y%m%d}{kind[0].upper()}{int(strike * 1000):08d}")


def pair_read(*contracts, spot=98.0, fetched=NOW - 20, spot_at=NOW - 10, simulated=False, issue=None):
    """Both expiries' chains as the one options-feed pass returns them."""
    from app.engine.options_models import OptionChain
    calls = []

    def read(symbol, old_expiry, new_expiry):
        calls.append((symbol, old_expiry, new_expiry))
        chains = {}
        for expiry in {c.expiration for c in contracts}:
            chains[expiry] = OptionChain(underlying=symbol, expiration=expiry, provider="tradier",
                                         fetched_at=datetime.fromtimestamp(fetched, UTC),
                                         contracts=tuple(c for c in contracts if c.expiration == expiry))
        return {"chains": chains, "fetched": {e: fetched for e in chains}, "spot": spot, "spot_at": spot_at,
                "spot_issue": None, "simulated": simulated, "issue": issue}
    read.calls = calls
    return read


def roll(*contracts, kind="call", old=(100.0, NOV21), new=(105.0, DEC19), held=3, read=None, **kw):
    kw.setdefault("now", NOW)
    return desk_roll.build("NBIS", kind, old[0], old[1], held, new[0], new[1], pair_read=read or pair_read(*contracts), **kw)


# --- the arithmetic: every case --------------------------------------------------------------------------------------

def test_a_call_rolled_up_and_out_for_a_debit():
    # Hold 3 NBIS 100C Nov 21 bought at 2.50 ($250 a contract). Close at the 4.00 mid, open the 105C Dec 19 at its 5.40
    # mid: 1.40 a share more, x100 x3 = $420 paid. Proceeds 4.00 x 300 = $1,200; the new contracts 5.40 x 300 = $1,620.
    f = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=3, open_qty=3, multiplier=100, close_price=4.00,
                               open_price=5.40, cost_per_contract=250, spot=98.0)
    assert (f["net"], f["net_type"], f["same_count"]) == (1.4, "debit", True)
    assert (f["proceeds"], f["cost"], f["net_usd"]) == (1200.0, 1620.0, 420.0)
    # Money in the trade: the $750 the 3 contracts cost, plus the $420 the roll pays, is $1,170.
    assert (f["basis_before"], f["in_trade_after"], f["ahead"]) == (750.0, 1170.0, False)
    # All a long option can still lose: what the old ones are worth now ($1,200), then what the new ones cost ($1,620).
    assert (f["at_risk_before"], f["at_risk_after"]) == (1200.0, 1620.0)
    # The new contract's break-even at its 5.40: 110.40, +12.65% from 98. The whole trade's: 105 + 1,170 / 300 = 108.90.
    assert (f["breakeven"], f["move_pct"], f["trade_breakeven"]) == (110.4, 12.65, 108.9)
    assert f["days_added"] == 28


def test_a_call_rolled_up_for_a_credit():
    # Hold 2 100C Nov 21 (cost $300 each), deep in the money at a 6.00 mid; roll to the 110C Dec 19 at 4.50: take in 1.50
    # a share, x200 = $300. Proceeds $1,200, the new ones $900; at risk $1,200 -> $900.
    f = desk_roll.roll_figures("call", 100, 110, NOV21, DEC19, close_qty=2, open_qty=2, multiplier=100, close_price=6.00,
                               open_price=4.50, cost_per_contract=300)
    assert (f["net"], f["net_type"], f["net_usd"]) == (1.5, "credit", -300.0)
    assert (f["proceeds"], f["cost"], f["at_risk_before"], f["at_risk_after"]) == (1200.0, 900.0, 1200.0, 900.0)
    # $600 in, $300 taken back out: $300 left in the trade, over 200 shares from the 110 strike = 111.50.
    assert (f["basis_before"], f["in_trade_after"], f["trade_breakeven"], f["breakeven"]) == (600.0, 300.0, 111.5, 114.5)


def test_a_put_rolled_down_and_out():
    # Hold 1 90P Nov 21 bought at 4.50; close at 2.10, open the 85P Dec 19 at 3.00: 0.90 debit, $90. A put's break-even
    # is under the strike: 85 - 3.00 = 82.00; the trade's, 85 - (450 + 90) / 100 = 79.60.
    f = desk_roll.roll_figures("put", 90, 85, NOV21, DEC19, close_qty=1, open_qty=1, multiplier=100, close_price=2.10,
                               open_price=3.00, cost_per_contract=450, spot=92.0)
    assert (f["net"], f["net_type"], f["net_usd"]) == (0.9, "debit", 90.0)
    assert (f["breakeven"], f["trade_breakeven"], f["in_trade_after"]) == (82.0, 79.6, 540.0)
    assert f["move_pct"] == round((82 - 92) / 92 * 100, 2)


def test_a_put_rolled_for_a_credit_signs_stay_right():
    # 95P worth 7.00 rolled to the 90P a month out at 5.20: a 1.80 credit, $180 in. 90 - 5.20 = 84.80 break-even.
    f = desk_roll.roll_figures("put", 95, 90, NOV21, DEC19, close_qty=1, open_qty=1, multiplier=100, close_price=7.00,
                               open_price=5.20, cost_per_contract=400)
    assert (f["net"], f["net_type"], f["net_usd"], f["in_trade_after"]) == (1.8, "credit", -180.0, 220.0)
    assert (f["breakeven"], f["trade_breakeven"]) == (84.8, 87.8)


def test_a_credit_bigger_than_the_cost_leaves_him_ahead():
    # Bought at 2.00, worth 8.00 now; rolled to a 1.00 contract: 7.00 credit, $700 in, $200 put in. $500 ahead: there is
    # no whole-trade break-even, the new contract is all upside.
    f = desk_roll.roll_figures("call", 100, 120, NOV21, DEC19, close_qty=1, open_qty=1, multiplier=100, close_price=8.00,
                               open_price=1.00, cost_per_contract=200)
    assert (f["net"], f["net_type"], f["net_usd"], f["in_trade_after"]) == (7.0, "credit", -700.0, -500.0)
    assert f["ahead"] is True and f["trade_breakeven"] is None and f["breakeven"] == 121.0


def test_the_typed_net_limit_sets_the_dollars_not_the_leg_mids():
    # Robinhood fills a roll at its net: a 1.25 debit typed against 4.00 / 5.40 mids moves $375 for 3, not $420.
    f = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=3, open_qty=3, multiplier=100, close_price=4.00,
                               open_price=5.40, net=1.25, cost_per_contract=250)
    assert (f["net"], f["net_usd"], f["at_risk_after"], f["in_trade_after"]) == (1.25, 375.0, 1575.0, 1125.0)
    assert f["trade_breakeven"] == 108.75  # 105 + 1,125 / 300
    # A typed credit is a negative net.
    c = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=3, open_qty=3, multiplier=100, close_price=4.00,
                               open_price=5.40, net=-0.30, cost_per_contract=250)
    assert (c["net"], c["net_type"], c["net_usd"], c["at_risk_after"]) == (0.3, "credit", -90.0, 1110.0)


def test_different_counts_are_two_orders_with_the_dollars_only():
    # Close 3 at 4.00 ($1,200), open 2 at 5.40 ($1,080): no one net a share, $120 taken in overall.
    f = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=3, open_qty=2, multiplier=100, close_price=4.00,
                               open_price=5.40, cost_per_contract=250)
    assert (f["same_count"], f["net"], f["net_type"]) == (False, None, None)
    assert (f["proceeds"], f["cost"], f["net_usd"], f["at_risk_after"]) == (1200.0, 1080.0, -120.0, 1080.0)
    # $750 in, $120 back: $630 over 200 new shares from 105 = 108.15.
    assert (f["in_trade_after"], f["trade_breakeven"]) == (630.0, 108.15)
    # A typed net is ignored for different counts: it cannot be one order.
    assert desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=3, open_qty=2, multiplier=100, close_price=4.00,
                                  open_price=5.40, net=1.0)["net_usd"] == -120.0


def test_the_multiplier_scales_and_no_count_or_no_cost_gives_fewer_figures():
    ten = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=1, open_qty=1, multiplier=10, close_price=4.00,
                                 open_price=5.40, cost_per_contract=25)
    assert (ten["proceeds"], ten["cost"], ten["net_usd"], ten["trade_breakeven"]) == (40.0, 54.0, 14.0, 108.9)
    bare = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=None, open_qty=None, multiplier=100,
                                  close_price=4.00, open_price=5.40)
    assert (bare["net"], bare["net_type"], bare["breakeven"]) == (1.4, "debit", 110.4)  # a share's figures still stand
    assert (bare["proceeds"], bare["net_usd"], bare["basis_before"], bare["trade_breakeven"]) == (None, None, None, None)
    no_cost = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=1, open_qty=1, multiplier=100,
                                     close_price=4.00, open_price=5.40)
    assert no_cost["net_usd"] == 140.0 and (no_cost["basis_before"], no_cost["in_trade_after"], no_cost["trade_breakeven"]) == (None, None, None)


def test_even_money_and_days_either_way():
    f = desk_roll.roll_figures("call", 100, 105, NOV21, NOV21, close_qty=1, open_qty=1, multiplier=100, close_price=3.00,
                               open_price=3.00)
    assert (f["net"], f["net_type"], f["net_usd"], f["days_added"]) == (0.0, "even", 0.0, 0)
    earlier = desk_roll.roll_figures("call", 100, 100, DEC19, NOV21, close_qty=1, open_qty=1, multiplier=100,
                                     close_price=5.0, open_price=3.0)
    assert earlier["days_added"] == -28 and earlier["net_type"] == "credit"


def test_rounding_is_to_the_cent_and_symmetric():
    assert desk_roll.signed_cents(1.405) == 1.41 and desk_roll.signed_cents(-1.405) == -1.41
    assert desk_roll.net_type(0.004) == "even" and desk_roll.net_type(-0.004) == "even"
    assert desk_roll.net_type(0.01) == "debit" and desk_roll.net_type(-0.01) == "credit"


def test_the_plain_line_and_the_copy_block():
    f = desk_roll.roll_figures("call", 100, 105, NOV21, DEC19, close_qty=1, open_qty=1, multiplier=100, close_price=4.00,
                               open_price=5.40)
    assert desk_roll.sentence("NBIS", "call", 100, NOV21, 105, DEC19, f) == \
        "Roll NBIS 100C Nov 21 → 105C Dec 19: pay $1.40 a share more ($140.00), break-even 110.40, 28 more days."
    c = desk_roll.roll_figures("put", 95, 90, NOV21, DEC19, close_qty=2, open_qty=2, multiplier=100, close_price=7.00, open_price=5.20)
    assert desk_roll.sentence("NBIS", "put", 95, NOV21, 90, DEC19, c) == \
        "Roll NBIS 95P Nov 21 → 90P Dec 19: take in $1.80 a share ($360.00), break-even 84.80, 28 more days."
    one = desk_roll.copy_text("NBIS", "call", 100, NOV21, 105, DEC19, close_qty=2, open_qty=2, net=1.4, net_type_="debit")
    assert one.splitlines() == ["NBIS · Roll", "Leg 1: Sell to close · NBIS $100 Call 11/21/26",
                                "Leg 2: Buy to open · NBIS $105 Call 12/19/26", "Limit price 1.40 debit", "Quantity 2"]
    two = desk_roll.copy_text("NBIS", "call", 100, NOV21, 105, DEC19, close_qty=3, open_qty=2, net=None, net_type_=None,
                              close_limit=4.0, open_limit=5.4)
    assert two.splitlines()[0] == "Order 1 of 2 · NBIS · Sell to close · NBIS $100 Call 11/21/26"
    assert "Order 2 of 2 · NBIS · Buy to open · NBIS $105 Call 12/19/26" in two and "Contracts 3" in two and "Contracts 2" in two


# --- the ticket: quotes from one pass --------------------------------------------------------------------------------

def test_the_ticket_prices_both_legs_from_one_read():
    read = pair_read(leg(100, NOV21, bid=3.90, ask=4.10), leg(105, DEC19, bid=5.30, ask=5.50))
    t = roll(read=read, held=3, cost_per_contract=250)
    assert read.calls == [("NBIS", NOV21, DEC19)]  # one pass for both expiries
    assert [l["action"] for l in t["legs"]] == ["sell_to_close", "buy_to_open"]
    assert (t["close_mid"], t["open_mid"]) == (4.0, 5.4)
    assert (t["net_mid"], t["net_mid_type"]) == (1.4, "debit")
    # Natural: sell the held one at its 3.90 bid, buy the new one at its 5.50 ask: 1.60 debit, the most he would pay.
    assert (t["net_natural"], t["net_natural_type"]) == (1.6, "debit")
    assert (t["figures"]["net_usd"], t["figures"]["breakeven"], t["figures"]["trade_breakeven"]) == (420.0, 110.4, 108.9)
    assert t["rough"] == [] and t["kept"] == 0 and t["multiplier"] == 100
    assert t["sentence"].startswith("Roll NBIS 100C Nov 21 → 105C Dec 19: pay $1.40 a share more ($420.00)")
    assert "Limit price 1.40 debit" in t["copy"] and "Quantity 3" in t["copy"]


def test_a_credit_rolls_natural_is_the_least_taken_in():
    t = roll(leg(100, NOV21, bid=5.90, ask=6.10), leg(110, DEC19, bid=4.40, ask=4.60), new=(110.0, DEC19), held=2)
    assert (t["net_mid"], t["net_mid_type"]) == (1.5, "credit")
    assert (t["net_natural"], t["net_natural_type"]) == (1.3, "credit")  # 4.60 - 5.90 = -1.30


def test_a_partial_roll_keeps_the_rest_and_the_new_count_follows():
    t = roll(leg(100, NOV21), leg(105, DEC19, bid=5.30, ask=5.50), held=5, close_qty=2)
    assert (t["close_qty"], t["open_qty"], t["kept"]) == (2, 2, 3)
    assert t["figures"]["net_usd"] == 280.0


def test_different_counts_copy_as_two_orders():
    t = roll(leg(100, NOV21), leg(105, DEC19, bid=5.30, ask=5.50), held=3, open_qty=2)
    assert t["figures"]["same_count"] is False and t["figures"]["net_usd"] == -120.0
    assert t["copy"].startswith("Order 1 of 2") and "Limit price 4.00" in t["copy"] and "Limit price 5.40" in t["copy"]


def test_a_stale_or_missing_leg_gives_no_net_and_says_why():
    stale = roll(leg(100, NOV21, quoted=NOW - 3600), leg(105, DEC19, bid=5.30, ask=5.50))
    assert stale["legs"][0]["quote"]["state"] == "stale" and "bid" not in stale["legs"][0]["quote"]
    assert stale["legs"][0]["quote"]["as_of"] == NOW - 3600  # its time is said
    assert (stale["net_mid"], stale["net_natural"], stale["sentence"], stale["figures"]["net_usd"]) == (None, None, None, None)
    assert stale["rough"] == ["the contract you hold has a stale quote"]
    assert stale["figures"]["breakeven"] == 110.4  # the new contract's own price still gives its break-even
    assert "Limit price (set it)" in stale["copy"]
    missing = roll(leg(100, NOV21))  # no Dec 19 chain at all
    assert missing["legs"][1]["quote"]["state"] == "missing" and missing["net_mid"] is None
    assert missing["rough"] == ["the new contract has no usable quote"]
    gone = roll(leg(100, NOV21), leg(110, DEC19))  # the chain has no 105
    assert gone["legs"][1]["quote"]["state"] == "missing"


def test_a_wide_leg_gives_a_rough_net():
    t = roll(leg(100, NOV21), leg(105, DEC19, bid=0.40, ask=0.60))
    assert t["net_mid"] == 3.5 and t["net_mid_type"] == "credit"
    assert t["rough"] == ["the new contract's market is wide (40% of its mid)"]


def test_different_multipliers_give_no_dollars():
    t = roll(leg(100, NOV21), leg(105, DEC19, multiplier=10))
    assert t["multiplier"] is None and t["figures"]["net_usd"] is None
    assert "different multipliers" in t["rough"][0]


@pytest.mark.parametrize("kw,why", [
    ({"kind": "straddle"}, "Only a long call or put"),
    ({"held": 0}, "no whole number"),
    ({"held": 2, "close_qty": 3}, "You hold 2"),
    ({"close_qty": 0}, "at least one"),
    ({"new": (100.0, NOV21)}, "the contract you hold"),
    ({"mode": "replay"}, "Replay"),
])
def test_rolls_this_build_does_not_price_are_refused_plainly(kw, why):
    with pytest.raises(desk_roll.RollError) as refused:
        roll(leg(100, NOV21), leg(105, DEC19), **kw)
    assert why in str(refused.value)


def test_the_live_read_asks_the_options_feed_once_for_both_expiries(monkeypatch):
    from app.engine import copilot_plans
    from app.engine.options_feed import options_feed
    from app.engine.options_models import OptionChain
    asked = []

    def chains(symbol, pick, *args, **kw):
        live = [date(2026, 11, 13), NOV21, DEC19, date(2027, 1, 15)]
        asked.append(pick(live))
        reads = [SimpleNamespace(value=OptionChain("NBIS", d, "tradier", datetime.fromtimestamp(NOW - 20, UTC), (leg(100 if d == NOV21 else 105, d),)),
                                 fetched=NOW - 20) for d in pick(live)]
        return reads, None
    monkeypatch.setattr(options_feed, "chains", chains)
    monkeypatch.setattr(copilot_plans, "_quotes", lambda symbols: ({"NBIS": 98.0}, NOW - 10, None))
    t = desk_roll.build("NBIS", "call", 100, NOV21, 1, 105, DEC19, now=NOW)
    assert asked == [[NOV21, DEC19]]  # one paced pass, only the two expiries the roll needs
    assert t["net_mid"] is not None and t["underlying"]["state"] == "ok"


# --- the route, and nothing sends ------------------------------------------------------------------------------------

def test_the_route_prices_the_fixture_and_refuses_plainly(engine, lab, monkeypatch):
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    params = {"symbol": "NBIS", "option_type": "call", "strike": 95, "expiration": "2026-11-20", "held": 2, "cost": 450,
              "new_strike": 100, "new_expiration": "2026-12-18"}
    body = lab.get("/copilot/roll", params=params).json()
    assert body["simulated"] is True and body["legs"][0]["quote"]["state"] == "ok" and body["net_mid"] is not None
    assert body["close_qty"] == 2 and body["figures"]["basis_before"] == 900.0
    assert lab.get("/copilot/roll", params={**params, "new_strike": 95, "new_expiration": "2026-11-20"}).status_code == 400
    assert lab.get("/copilot/roll", params={**params, "quantity": 3}).status_code == 400
    assert lab.get("/copilot/roll", params={**params, "option_type": "straddle"}).status_code == 422
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/roll", params=params).status_code == 503


def test_the_roll_never_sends_and_never_reads_robinhood():
    sources = [inspect.getsource(desk_roll), (REPO / "frontend/components/copilot/DeskRoll.tsx").read_text(),
               (REPO / "frontend/lib/rollTicket.ts").read_text()]
    forbidden = ("robinhood_read", "robinhood_trading", "place_option_order", "review_option_order", "order_tool",
                 "requests.post", "httpx", "urllib", "method: \"POST\"", "method: 'POST'", "ntfy", "telegram", "Send to")
    for text in sources:
        assert not [word for word in forbidden if word.lower() in text.lower()]
    math = (REPO / "frontend/lib/rollTicket.ts").read_text()
    assert "fetch(" not in math and "apiUrl" not in math and "deskGet" not in math
    # Read only: the roll route answers GET and nothing else.
    methods = {m for route in ticket_routes.router.routes if getattr(route, "path", "") == "/roll" for m in route.methods}
    assert methods <= {"GET", "HEAD"}
