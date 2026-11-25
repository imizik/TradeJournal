"""Should I add? The record of adds below cost (publisher side) and the answer for one open position."""
from datetime import date, datetime

from app.engine import add_check, fill_interrupts

NOW = datetime(2026, 11, 24, 11, 30)  # naive New York
EXPIRY = date(2026, 11, 24)


def fill(key, seq, role, side, contracts, price, at, *, status="closed", pnl=0.0, expiration=EXPIRY, ticker="SPY"):
    return {"trade_key": key, "seq": seq, "role": role, "side": side, "contracts": contracts, "price": price,
            "executed_at": at, "ticker": ticker, "option_type": "call", "expiration": expiration, "status": status,
            "realized_pnl": pnl, "closed_at": datetime(2026, 11, 20, 15, 0)}


def position_view(*, mid, dte=0, held=90, entry=200.0, instrument="option"):
    return {"position": {"ticker": "spy", "instrument_type": instrument, "option_type": "call" if instrument == "option" else None,
                         "avg_entry_premium": entry, "contracts": 2.0, "total_premium_paid": entry * 2},
            "option": {"mid": mid} if mid else None, "days_to_expiration": dte, "held_minutes": held,
            "mark": {"unrealized_pnl": None}}


def row(pnl, add_pnl, *, dte=0, below=30.0, closed="2026-11-10T15:00:00", ticker="SPY"):
    return {"closed_at": closed, "underlying": ticker, "side": "call", "realized_pnl": pnl,
            "adds": [{"dte": dte, "below_cost_pct": below, "minutes_held": 75, "premium": 100.0, "pnl": add_pnl}]}


def test_history_rows_split_the_added_contracts_first_in_first_out():
    day = datetime(2026, 11, 20, 10, 0)
    records = [
        # Bought 1 at $200, added 1 at $100 (50% below cost), sold both at $120: the add made $20, the position lost $60.
        fill("a", 1, "entry", "buy_to_open", 1, 200.0, day, pnl=-60.0, expiration=date(2026, 11, 21)),
        fill("a", 2, "entry", "buy_to_open", 1, 100.0, day.replace(hour=11, minute=15), pnl=-60.0, expiration=date(2026, 11, 21)),
        fill("a", 3, "exit", "sell_to_close", 2, 120.0, day.replace(hour=12), pnl=-60.0, expiration=date(2026, 11, 21)),
        # Added below cost, sold the first contract, the added one expired worthless.
        fill("b", 2, "entry", "buy_to_open", 1, 50.0, day.replace(hour=13), status="expired", pnl=-140.0, expiration=date(2026, 11, 20)),
        fill("b", 1, "entry", "buy_to_open", 1, 100.0, day, status="expired", pnl=-140.0, expiration=date(2026, 11, 20)),
        fill("b", 3, "exit", "sell_to_close", 1, 10.0, day.replace(hour=14), status="expired", pnl=-140.0, expiration=date(2026, 11, 20)),
        # A second buy above cost is not an add below cost; a short is never read.
        fill("c", 1, "entry", "buy_to_open", 1, 100.0, day), fill("c", 2, "entry", "buy_to_open", 1, 130.0, day),
        fill("c", 3, "exit", "sell_to_close", 2, 150.0, day),
        fill("d", 1, "entry", "sell_to_open", 1, 100.0, day), fill("d", 2, "entry", "sell_to_open", 1, 80.0, day),
        # Closed with a contract the fills never sold: unexplained, so not counted.
        fill("e", 1, "entry", "buy_to_open", 1, 100.0, day), fill("e", 2, "entry", "buy_to_open", 1, 80.0, day),
        fill("e", 3, "exit", "sell_to_close", 1, 90.0, day),
    ]
    rows = add_check.add_history_rows(records)
    assert [(r["realized_pnl"], r["adds"]) for r in rows] == [
        (-140.0, [{"dte": 0, "below_cost_pct": 50.0, "minutes_held": 180, "premium": 50.0, "pnl": -50.0}]),
        (-60.0, [{"dte": 1, "below_cost_pct": 50.0, "minutes_held": 75, "premium": 100.0, "pnl": 20.0}])]
    assert all(set(r) == add_check.ADD_ROW_KEYS and set(r["adds"][0]) == add_check.ADD_KEYS for r in rows)
    # The same below-cost test the fill-time interrupt uses.
    journal = [{"id": 1, "side": "buy_to_open", "instrument_type": "option", "contracts": 1, "price": 200.0, "executed_at": day}]
    add = {"id": 2, "side": "buy_to_open", "instrument_type": "option", "contracts": 1, "price": 100.0, "executed_at": day}
    assert fill_interrupts.adds_to_loser(add, journal) and not fill_interrupts.adds_to_loser({**add, "price": 200.0}, journal)


def test_answer_is_no_when_the_added_contracts_lost_money_in_this_kind_of_spot():
    rows = [row(-150.0, -80.0) for _ in range(8)] + [row(40.0, 25.0, dte=10), row(500.0, 300.0, closed="2026-12-01T15:00:00")]
    view = add_check.add_view(position_view(mid=1.5), rows, NOW)  # $150 against a $200 entry: 25% below cost
    assert view["answer"] == "no" and view["headline"].startswith("No. ")
    assert view["now"]["pct_vs_cost"] == -25.0 and view["leak_pattern"]["all_three"] is True
    decided = view["record"]["cohorts"][0]
    assert view["record"]["decided_by"] == decided["name"] == "short_dated_down_20_or_more"
    # The longer-dated add and the position closed after this moment are left out.
    assert decided["positions"] == 8 and decided["ended_green"] == 0 and decided["position_pnl"] == -1200.0
    assert decided["added_contracts_pnl"] == -640.0 and decided["added_premium"] == 800.0
    assert "$640" in view["headline"] and len(view["record"]["recent"]) == 5
    assert view["record"]["cohorts"][2]["name"] == "short_dated_same_ticker" and view["record"]["cohorts"][2]["positions"] == 8


def test_small_or_winning_records_never_say_no_and_never_say_go():
    few = add_check.add_view(position_view(mid=1.5), [row(-150.0, -80.0) for _ in range(7)], NOW)
    assert few["answer"] == "no_clear_record" and few["record"]["decided_by"] is None and "Too few" in few["headline"]
    won = add_check.add_view(position_view(mid=1.5), [row(90.0, 60.0) for _ in range(8)], NOW)
    assert won["answer"] == "no_clear_record" and "not a go" in won["headline"] and "$+480" in won["headline"]
    # A shallow dip falls back to every short-dated add when its own depth group is too small.
    shallow = add_check.add_view(position_view(mid=1.9, held=20), [row(-150.0, -80.0) for _ in range(8)], NOW)
    assert shallow["answer"] == "no" and shallow["record"]["decided_by"] == "short_dated"
    assert shallow["leak_pattern"] == {**shallow["leak_pattern"], "down_20_or_more": False, "held_over_an_hour": False,
                                       "all_three": False}
    # Longer-dated positions read only longer-dated adds.
    longer = add_check.add_view(position_view(mid=1.5, dte=10), [row(-150.0, -80.0) for _ in range(8)], NOW)
    assert longer["answer"] == "no_clear_record" and longer["record"]["cohorts"][1] == {
        "name": "longer_dated", "positions": 0, "enough": False}


def test_positions_the_record_does_not_cover_are_named_not_guessed():
    rows = [row(-150.0, -80.0) for _ in range(8)]
    assert add_check.add_view(position_view(mid=2.5), rows, NOW)["answer"] == "not_below_cost"
    assert add_check.add_view(position_view(mid=None), rows, NOW)["answer"] == "insufficient_data"
    assert add_check.add_view(position_view(mid=1.5), None, NOW)["answer"] == "insufficient_data"
    shares = add_check.add_view(position_view(mid=1.5, instrument="stock"), rows, NOW)
    assert shares["answer"] == "not_covered" and shares["record"] is None
