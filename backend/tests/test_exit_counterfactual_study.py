"""Exit counterfactual study on synthetic option bars: triggers, fills, costs
and decisions, with hand-calculated dollars."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import random

import pytest

from scripts import exit_counterfactual_study as s

DAY = date(2026, 5, 6)


def at(hhmm: str, day: date = DAY) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), s.ET).astimezone(UTC)


def bar(hhmm: str, o, c=None, day: date = DAY) -> dict:
    return {"t": at(hhmm, day), "o": Decimal(str(o)), "c": Decimal(str(c if c is not None else o))}


def fill(side: str, hhmm: str, contracts, price, day: date = DAY, seconds: int = 30) -> dict:
    return {"side": side, "contracts": Decimal(str(contracts)), "price": Decimal(str(price)),
            "at": at(hhmm, day) + timedelta(seconds=seconds), "role": "entry" if side == s.ENTRY else "exit"}


def trade(status="closed", expiration=date(2026, 5, 8)) -> dict:
    return {"id": "t1", "status": status, "expiration": expiration, "closed_at": None}


def minutes(start: str, prices: list) -> list[dict]:
    first = at(start)
    return [{"t": first + timedelta(minutes=i), "o": Decimal(str(p)), "c": Decimal(str(p))} for i, p in enumerate(prices)]


def test_giveback_arms_at_ten_percent_and_fifty_dollars_then_sells_next_open():
    # 5 contracts at $1.00: $500 premium. 1.20 is +20% and +$100 (armed); 1.02 is +2% (fires).
    fills = [fill(s.ENTRY, "10:00", 5, 100), fill(s.EXIT, "10:30", 5, 50)]
    bars = minutes("10:01", [1.10, 1.20, 1.15, 1.02, 1.01, 0.90])
    row = s.simulate_trade(trade(), fills, bars, random.Random(1))
    g = row["rules"]["giveback"]
    assert g["trigger_at"] == at("10:05").isoformat()  # the 1.02 bar (10:04) closes at 10:05
    assert g["exit_at"] == at("10:05").isoformat()
    # 101 - max(3% of 101, $1) = 97.97 a contract; 5 x (97.97 - 100) = -10.15 against -250 actual.
    assert g["exit_price"] == pytest.approx(97.97)
    assert row["actual_pnl"] == -250
    assert g["diff"] == pytest.approx(239.85)
    # Stress: 101 - 9.09 = 91.91; 5 x -8.09 = -40.45.
    assert g["diff_stress"] == pytest.approx(209.55)


def test_giveback_needs_fifty_dollars_as_well_as_ten_percent():
    fills = [fill(s.ENTRY, "10:00", 1, 100), fill(s.EXIT, "10:30", 1, 50)]
    bars = minutes("10:01", [1.30, 1.00, 0.90])  # +30% is only $30
    assert s.simulate_trade(trade(), fills, bars, random.Random(1))["rules"]["giveback"] is None


def test_a_bar_holding_a_fill_is_not_judged():
    fills = [fill(s.ENTRY, "10:00", 5, 100), fill(s.ENTRY, "10:02", 5, 100), fill(s.EXIT, "10:30", 10, 50)]
    bars = minutes("10:00", [1.0, 1.0, 1.5, 1.0])
    judged = s.judged_bars(s.Position(fills), bars, at("10:30"))
    assert [b["t"] for b, _, _ in judged] == [at("10:01"), at("10:03")]


def test_hold_hour_sells_at_sixty_minutes_and_keeps_an_earlier_partial_exit():
    fills = [fill(s.ENTRY, "10:00", 4, 200, seconds=0), fill(s.EXIT, "10:20", 2, 300), fill(s.EXIT, "14:00", 2, 100)]
    bars = [bar("10:59", 2.5), bar("11:00", 2.5), bar("11:01", 2.4)]
    row = s.simulate_trade(trade(), fills, bars, random.Random(1))
    h = row["rules"]["hold_hour"]
    assert h["exit_at"] == at("11:00").isoformat()
    # Realized 2 x 100 = 200; rest 2 x (250 - 7.5 - 200) = 85; actual 200 - 200 = 0.
    assert row["actual_pnl"] == 0
    assert h["diff"] == pytest.approx(285)
    assert h["cf_pct"] == pytest.approx(285 / 800 * 100)


def test_no_bar_within_five_minutes_means_the_actual_exit_stands():
    fills = [fill(s.ENTRY, "10:00", 1, 200, seconds=0), fill(s.EXIT, "14:00", 1, 100)]
    bars = [bar("10:30", 2.0), bar("11:05", 2.5)]
    assert s.simulate_trade(trade(), fills, bars, random.Random(1))["rules"]["hold_hour"] is None


def test_hold_hour_counts_a_premarket_entry_from_the_open_and_only_on_the_entry_day():
    p = s.Position([fill(s.ENTRY, "08:00", 1, 100)])
    assert s.trigger_time("hold_hour", trade(), p, []) == at("10:30")
    late = s.Position([fill(s.ENTRY, "15:10", 1, 100)])
    assert s.trigger_time("hold_hour", trade(), late, []) is None


def test_expiry_day_fires_ninety_minutes_before_the_close_including_half_days():
    p = s.Position([fill(s.ENTRY, "10:00", 1, 100)])
    assert s.trigger_time("expiry_day", trade(expiration=DAY), p, []) == at("14:30")
    half = date(2025, 11, 28)
    assert s.trigger_time("expiry_day", trade(expiration=half), p, []) == at("11:30", half)


def test_an_expired_trade_counts_what_was_left_open_as_worthless():
    fills = [fill(s.ENTRY, "10:00", 2, 150, day=date(2026, 5, 8))]
    bars = [bar("14:30", 0.20, day=date(2026, 5, 8))]
    row = s.simulate_trade(trade(status="expired", expiration=date(2026, 5, 8)), fills, bars, random.Random(1))
    assert row["actual_pnl"] == -300
    # 20 - $1 minimum = 19 a contract: 2 x (19 - 150) = -262.
    assert row["rules"]["expiry_day"]["diff"] == pytest.approx(38)


def test_an_exit_without_an_open_lot_is_refused():
    with pytest.raises(ValueError):
        s.Position([fill(s.ENTRY, "10:00", 1, 100), fill(s.EXIT, "10:05", 2, 100)]).state(at("11:00"))


def test_decisions_follow_the_registered_criteria():
    period = {"touched": 5, "dollar_diff": 10, "pct_diff_mean": 1}
    full = {"touched": 10, "dollar_diff_interval": [5, 50], "dollar_diff_stress": 3, "timing_value_interval": [1, 9]}
    assert s.decide(full, {"a": period, "b": period}).startswith("eligible")
    assert s.decide({**full, "timing_value_interval": [-1, 9]}, {"a": period, "b": period}).startswith("investigate")
    assert s.decide({**full, "dollar_diff_stress": -1}, {"a": period, "b": period}).startswith("reject as")
    assert s.decide(full, {"a": period, "b": {**period, "pct_diff_mean": -1}}).startswith("reject as")
    assert s.decide({**full, "dollar_diff_interval": [-50, -5]}, {"a": period}).startswith("reject: following")


def test_the_extract_is_one_read_only_transaction():
    sql = s.EXTRACT_SQL.upper()
    assert "BEGIN READ ONLY" in sql
    for word in ("INSERT", "UPDATE ", "DELETE", "DROP", "ALTER", "TRUNCATE"):
        assert word not in sql


def test_bootstrap_interval_contains_a_constant_total():
    low, high = s.day_bootstrap({"a": [1.0], "b": [1.0]}, s.total, random.Random(1))
    assert low == high == 2.0


def test_occ_symbol():
    assert s.occ("SPY", date(2026, 10, 9), "put", 774) == "SPY261009P00774000"
    assert s.occ("BRK.B", date(2026, 1, 16), "call", 512.5) == "BRKB260116C00512500"


def test_run_end_to_end_from_an_extract_and_a_cached_window(tmp_path):
    import json

    def contract(n):
        return {"id": f"t{n}", "ticker": "SPY", "option_type": "call", "strike": 700, "expiration": "2026-05-08",
                "status": "closed", "opened_at": "2026-05-06T10:00:00", "closed_at": "2026-05-06T10:30:00",
                "realized_pnl": -250, "total_premium_paid": 500, "account_type": "roth_ira"}

    fills = []
    for n in (1, 2):
        fills += [{"trade_id": f"t{n}", "fill_id": f"e{n}", "role": "entry", "side": "buy_to_open",
                   "contracts": 5, "price": 100, "executed_at": "2026-05-06T10:00:30"},
                  {"trade_id": f"t{n}", "fill_id": f"x{n}", "role": "exit", "side": "sell_to_close",
                   "contracts": 5, "price": 50, "executed_at": "2026-05-06T10:30:00"}]
    unbarred = {**contract(3), "id": "t3", "strike": 701}
    fills += [{**fills[0], "trade_id": "t3", "fill_id": "e3"}, {**fills[1], "trade_id": "t3", "fill_id": "x3"}]
    short = {**contract(4), "id": "t4"}
    fills += [{**fills[0], "trade_id": "t4", "fill_id": "e4", "side": "sell_to_open"}]
    extract = tmp_path / "trades.json"
    extract.write_text(json.dumps({"protocol_id": s.PROTOCOL_ID, "trades": [contract(1), contract(2), unbarred, short],
                                   "fills": fills}))
    folder = tmp_path / "cache" / "options" / "1Min" / "SPY260508C00700000"
    folder.mkdir(parents=True)
    raw = [{"t": (at("10:01") + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"), "o": p, "c": p}
           for i, p in enumerate([1.10, 1.20, 1.15, 1.02, 1.01, 0.90])]
    (folder / "2026-05-06T100000-0400_2026-05-06T103000-0400.json").write_text(json.dumps(raw))

    results = s.run(extract, tmp_path / "cache", tmp_path / "out", fetch=False)
    assert results["analyzed"] == 2
    assert results["excluded"] == {"no option minute bars": 1,
                                   "not a long option (side other than buy_to_open/sell_to_close)": 1}
    assert results["recorded_pnl_mismatch"] == 0
    g = results["rules"]["giveback"]["all"]
    assert g["touched"] == 2 and g["dollar_diff"] == pytest.approx(479.7)
    assert g["dollar_diff_interval"] == [pytest.approx(479.7), pytest.approx(479.7)]  # one day
    assert results["rules"]["giveback"]["check"]["touched"] == 2
    assert results["rules"]["giveback"]["exploration"]["touched"] == 0
    assert (tmp_path / "out" / "results.json").exists()
    import hashlib
    import re
    prov = results["provenance"]
    assert prov["protocol_id"] == s.PROTOCOL_ID
    assert prov["extract_sha256"] == hashlib.sha256(extract.read_bytes()).hexdigest()
    assert prov["source_sha"] is None or re.fullmatch(r"[0-9a-f]{40}", prov["source_sha"])
