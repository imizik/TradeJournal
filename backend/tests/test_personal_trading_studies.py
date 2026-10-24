"""Stop-after-green, size-cap and long-holds studies on synthetic extracts and
daily bars, with hand-calculated dollars."""

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random

import pytest

from scripts import exit_counterfactual_study as x
from scripts import personal_trading_studies as s


def fills_for(tid: str, legs: list[tuple]) -> list[dict]:
    """legs: (side, executed_at, contracts, price) with price in dollars per contract."""
    return [{"trade_id": tid, "fill_id": f"{tid}-{i}", "role": "entry" if side == x.ENTRY else "exit",
             "side": side, "contracts": qty, "price": price, "executed_at": stamp}
            for i, (side, stamp, qty, price) in enumerate(legs)]


def contract(tid: str, opened: str, closed: str, pnl=None, status="closed", expiration="2026-08-21", strike=700) -> dict:
    return {"id": tid, "ticker": "SPY", "option_type": "call", "strike": strike, "expiration": expiration,
            "status": status, "opened_at": opened, "closed_at": closed, "realized_pnl": pnl,
            "total_premium_paid": None, "account_type": "roth_ira"}


def round_trip(tid: str, opened: str, closed: str, qty, entry, exit_price) -> tuple[dict, list[dict]]:
    pnl = qty * (exit_price - entry)
    return contract(tid, opened, closed, pnl), fills_for(tid, [(x.ENTRY, opened, qty, entry), (x.EXIT, closed, qty, exit_price)])


def write_extract(tmp_path, pairs) -> Path:
    trades = [t for t, _ in pairs]
    fills = [f for _, own in pairs for f in own]
    path = tmp_path / "trades.json"
    path.write_text(json.dumps({"protocol_id": x.PROTOCOL_ID, "trades": trades, "fills": fills}))
    return path


def load(tmp_path, pairs) -> list[dict]:
    trades, excluded = s.load_trades(write_extract(tmp_path, pairs))
    assert excluded == {}
    return trades


def ids(trades, skipped):
    return sorted(t["id"] for t in trades if t["id"] in skipped)


# ---------------------------------------------------------------- stop after green

GREEN_DAY = [
    round_trip("A", "2026-05-06T10:00:00", "2026-05-06T10:30:00", 1, 100, 400),  # +300 lifts the day
    round_trip("B", "2026-05-06T10:45:00", "2026-05-06T11:00:00", 1, 200, 100),  # -100, after the trigger
    round_trip("C", "2026-05-06T10:30:00", "2026-05-06T12:00:00", 1, 100, 150),  # +50, entered at the trigger
    round_trip("D", "2026-05-06T13:00:00", "2026-05-06T14:00:00", 1, 100, 0),    # -100, after the trigger
]


def test_stop_skips_entries_strictly_after_the_close_that_lifts_the_day(tmp_path):
    trades = load(tmp_path, GREEN_DAY)
    assert ids(trades, s.stop_skips(trades, s.STOP_RULES["stop_above_0"])) == ["B", "D"]
    assert ids(trades, s.stop_skips(trades, s.STOP_RULES["stop_above_250"])) == ["B", "D"]
    # 300, then 200, 250, 150: never above 500.
    assert s.stop_skips(trades, s.STOP_RULES["stop_above_500"]) == set()


def test_closes_at_the_same_instant_count_together(tmp_path):
    trades = load(tmp_path, [
        round_trip("E", "2026-05-06T10:00:00", "2026-05-06T11:00:00", 1, 100, 700),  # +600
        round_trip("F", "2026-05-06T10:05:00", "2026-05-06T11:00:00", 1, 800, 100),  # -700 at the same instant
        round_trip("G", "2026-05-06T11:30:00", "2026-05-06T12:00:00", 1, 100, 50),
    ])
    assert s.stop_skips(trades, s.STOP_RULES["stop_above_0"]) == set()


def test_a_skipped_multi_day_trade_never_counts_toward_a_later_day(tmp_path):
    trades = load(tmp_path, [
        round_trip("A", "2026-05-06T10:00:00", "2026-05-06T10:30:00", 1, 100, 200),  # +100 on day 1
        round_trip("B", "2026-05-06T11:00:00", "2026-05-07T10:00:00", 1, 100, 700),  # +600, closes day 2
        round_trip("C", "2026-05-07T10:30:00", "2026-05-07T11:00:00", 1, 100, 50),
    ])
    # Above $0 on day 1 skips B, so day 2 never turns green and C is taken.
    assert ids(trades, s.stop_skips(trades, s.STOP_RULES["stop_above_0"])) == ["B"]
    # $100 is not above $250: B is taken, closes +600 on day 2 at 10:00 and C is skipped.
    assert ids(trades, s.stop_skips(trades, s.STOP_RULES["stop_above_250"])) == ["C"]
    assert ids(trades, s.stop_skips(trades, s.STOP_RULES["stop_above_500"])) == ["C"]


def test_stop_summary_dollars_return_on_premium_and_flat_cut(tmp_path):
    trades = load(tmp_path, GREEN_DAY)
    factors = s.stop_factors(trades)
    records = [s.scaled_record(t, {r: factors[r][t["id"]] for r in s.STOP_RULES}) for t in trades]
    out = s.summarize_scaled(records, "stop_above_0", random.Random(1), s.STOP_LEVEL)
    # Skipping B (-100) and D (-100) keeps $200. Premium 500 -> 200; P&L 150 -> 350.
    assert out["affected"] == 2 and out["dollar_diff"] == 200
    assert out["rop_actual"] == 30 and out["rop_counterfactual"] == 175 and out["rop_diff"] == 145
    # Skipped mean (-50% and -100%) is -75%; kept mean (300% and 50%) is 175%.
    assert out["pct_gap"] == -250
    # The same premium cut evenly: every trade at 200/500, so (0.4 - 1) x 150 = -90; selection 200 + 90.
    assert out["flat_cut_diff"] == -90 and out["selection_value"] == 290
    assert out["dollar_diff_interval"] == [200, 200] and out["selection_value_interval"] == [290, 290]  # one day
    assert out["largest_loss"] == [-100, 0]  # the skipped losers are gone
    assert out["worst_day"] == [150, 350]


def test_stop_decisions_follow_the_registered_criteria():
    period = {"affected": 3, "dollar_diff": 10, "rop_diff": 1, "pct_gap": -2}
    full = {"affected": 6, "dollar_diff_interval": [5, 50], "selection_value_interval": [1, 9]}
    both = {"exploration": period, "check": period}
    assert s.decide_stop(full, both).startswith("eligible")
    assert s.decide_stop({**full, "selection_value_interval": [-1, 9]}, both).startswith("investigate")
    assert s.decide_stop(full, {**both, "check": {**period, "pct_gap": 1}}).startswith("reject as")
    assert s.decide_stop(full, {**both, "check": {**period, "affected": 0}}).startswith("reject as")
    assert s.decide_stop({**full, "dollar_diff_interval": [-5, 50]}, both).startswith("reject as")
    assert s.decide_stop({**full, "dollar_diff_interval": [-50, -5]}, both).startswith("reject: stopping")
    assert s.decide_stop({**full, "affected": 0}, both) == "no trades skipped"


# ---------------------------------------------------------------- size cap


def capped_population() -> list:
    # Twenty warm-up trades, ten at $100 and ten at $300 premium, all flat; the median is $200.
    pairs = [round_trip(f"w{i:02d}", f"2026-05-06T10:{i:02d}:00", f"2026-05-06T15:{i:02d}:00", 1,
                        100 if i % 2 else 300, 100 if i % 2 else 300) for i in range(20)]
    # The 21st pays $1,000 and loses $500.
    pairs.append(round_trip("big", "2026-05-06T11:00:00", "2026-05-06T12:00:00", 1, 1000, 500))
    return pairs


def test_cap_scales_a_trade_above_the_trailing_median_and_spares_the_warmup(tmp_path):
    trades = load(tmp_path, capped_population())
    refs = s.cap_references(trades)
    assert refs["big"] == 200
    assert all(refs[f"w{i:02d}"] is None for i in range(20))
    factors = s.cap_factors(trades)
    assert factors["cap_1_5x"]["big"] == Decimal("0.3")  # 1.5 x 200 / 1000
    assert factors["cap_2x"]["big"] == Decimal("0.4")
    assert all(factors["cap_1_5x"][f"w{i:02d}"] == 1 for i in range(20))  # $300 trades are uncapped warm-up


def test_cap_summary_dollars_return_on_premium_and_flat_cut(tmp_path):
    trades = load(tmp_path, capped_population())
    factors = s.cap_factors(trades)
    records = [s.scaled_record(t, {r: factors[r][t["id"]] for r in s.CAP_RULES}) for t in trades]
    out = s.summarize_scaled(records, "cap_1_5x", random.Random(1), s.CAP_LEVEL)
    # -500 x 0.3 = -150, so the cap keeps $350. Premium 5,000 -> 4,300.
    assert out["affected"] == 1 and out["dollar_diff"] == pytest.approx(350)
    assert out["rop_actual"] == -10 and out["rop_counterfactual"] == pytest.approx(-150 / 4300 * 100, abs=0.01)
    # Flat cut to 4,300/5,000 of every trade: (0.86 - 1) x -500 = +70; selection 350 - 70.
    assert out["flat_cut_diff"] == pytest.approx(70) and out["selection_value"] == pytest.approx(280)
    assert out["largest_loss"] == [-500, -150]
    out2 = s.summarize_scaled(records, "cap_2x", random.Random(1), s.CAP_LEVEL)
    assert out2["dollar_diff"] == pytest.approx(300)


def test_the_reference_counts_only_premium_paid_before_the_trade_opens(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "TRAILING", 1)
    p = contract("P", "2026-05-06T10:00:00", "2026-05-06T15:00:00")
    q, q_fills = round_trip("Q", "2026-05-06T11:00:00", "2026-05-06T12:00:00", 1, 100, 100)
    p_fills = fills_for("P", [(x.ENTRY, "2026-05-06T10:00:00", 1, 100), (x.ENTRY, "2026-05-06T11:30:00", 1, 100),
                              (x.EXIT, "2026-05-06T15:00:00", 2, 100)])
    trades = load(tmp_path, [(p, p_fills), (q, q_fills)])
    assert s.cap_references(trades)["Q"] == 100  # P's 11:30 add comes after Q opens


def test_cap_decisions_follow_the_registered_criteria():
    period = {"affected": 3, "dollar_diff": 10, "rop_diff": 1}
    full = {"affected": 6, "dollar_diff_interval": [5, 50], "selection_value_interval": [1, 9]}
    both = {"exploration": period, "check": period}
    assert s.decide_cap(full, both).startswith("eligible")
    assert s.decide_cap({**full, "selection_value_interval": [-1, 9]}, both).startswith("investigate")
    assert s.decide_cap(full, {**both, "exploration": {**period, "rop_diff": -1}}).startswith("reject as")
    assert s.decide_cap({**full, "dollar_diff_interval": [-50, -5]}, both).startswith("reject: the cap")


def test_scaled_runs_end_to_end_with_receipts(tmp_path):
    path = write_extract(tmp_path, GREEN_DAY + [
        (contract("short", "2026-05-06T10:00:00", "2026-05-06T11:00:00"),
         fills_for("short", [("sell_to_open", "2026-05-06T10:00:00", 1, 100)]))])
    results = s.run_stop(path, tmp_path / "out")
    assert results["analyzed"] == 4 and results["extract_trades"] == 5
    assert results["excluded"] == {"not a long option (side other than buy_to_open/sell_to_close)": 1}
    assert results["recorded_pnl_mismatch"] == 0
    rule = results["rules"]["stop_above_0"]
    assert rule["all"]["dollar_diff"] == 200 and rule["check"]["affected"] == 2 and rule["exploration"]["affected"] == 0
    assert rule["decision"].startswith("reject as")  # no exploration-period skips
    assert results["rules"]["stop_above_500"]["decision"] == "no trades skipped"
    prov = results["provenance"]
    assert prov["protocol_id"] == s.STOP_ID and prov["extract_is_registered"] is False
    assert prov["extract_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (tmp_path / "out" / "stop-after-green" / "results.json").exists()
    assert len((tmp_path / "out" / "stop-after-green" / "trades.jsonl").read_text().splitlines()) == 4
    cap = s.run_cap(path, tmp_path / "out")
    assert cap["protocol_id"] == s.CAP_ID and cap["rules"]["cap_2x"]["decision"] == "no trades capped"


def test_the_extract_must_be_the_exit_study_extract(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"protocol_id": "something-else", "trades": [], "fills": []}))
    with pytest.raises(SystemExit):
        s.load_trades(path)


# ---------------------------------------------------------------- long holds


def daily(day: str, c) -> dict:
    return {"t": f"{day}T04:00:00Z", "o": c, "c": c}


# Session 1 is Thursday July 2; July 3 is a holiday, so 2 = July 6, 3 = July 7, 4 = July 8, 5 = July 9.
LONG_BARS = [daily("2026-07-02", 2.50), daily("2026-07-06", 2.00), daily("2026-07-08", 1.80),
             daily("2026-07-09", 1.00), daily("2026-07-10", 0.90)]


def long_trade(tmp_path, legs=None, closed="2026-07-20T14:00:00"):
    legs = legs or [(x.ENTRY, "2026-07-02T10:00:00", 2, 300), (x.EXIT, closed, 2, 50)]
    trades = load(tmp_path, [(contract("L", "2026-07-02T10:00:00", closed), fills_for("L", legs))])
    return trades[0]


def test_sessions_skip_weekends_and_holidays():
    assert s.sessions_from(date(2026, 7, 2), 5) == [date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 7),
                                                    date(2026, 7, 8), date(2026, 7, 9)]


def test_long_hold_exits_at_session_closes_with_the_spread_haircut(tmp_path):
    trade = long_trade(tmp_path)
    assert trade["window_days"] == 19
    row = s.simulate_long(trade, [x.parse_bar(b) for b in LONG_BARS])
    assert row["actual_pnl"] == -500
    one = row["rules"]["exit_session_1"]
    # 250 - 3% = 242.50 a contract: 2 x (242.50 - 300) = -115 against -500.
    assert one["exit_day"] == "2026-07-02" and one["diff"] == pytest.approx(385)
    # Stress: 250 - 22.50 = 227.50; 2 x -72.50 = -145.
    assert one["diff_stress"] == pytest.approx(355)
    assert one["cf_pct"] == pytest.approx(-115 / 600 * 100)
    # Session 3 (July 7) has no bar, so July 8: 180 - 5.40 = 174.60; 2 x -125.40 = -250.80.
    three = row["rules"]["exit_session_3"]
    assert three["exit_day"] == "2026-07-08" and three["diff"] == pytest.approx(249.2)
    # Session 5 (July 9): 100 - 3 = 97; 2 x -203 = -406.
    assert row["rules"]["exit_session_5"]["diff"] == pytest.approx(94)


def test_long_hold_counts_adds_before_the_exit_and_drops_later_fills(tmp_path):
    trade = long_trade(tmp_path, [(x.ENTRY, "2026-07-02T10:00:00", 1, 300), (x.ENTRY, "2026-07-06T11:00:00", 1, 200),
                                  (x.EXIT, "2026-07-08T10:00:00", 1, 400), (x.EXIT, "2026-07-20T14:00:00", 1, 50)])
    row = s.simulate_long(trade, [x.parse_bar(b) for b in LONG_BARS])
    # Actual: FIFO sells the $300 lot at 400 (+100), the $200 lot at 50 (-150).
    assert row["actual_pnl"] == -50
    # Session 1: only the first lot, 242.50 - 300 = -57.50.
    assert row["rules"]["exit_session_1"]["diff"] == pytest.approx(-7.5)
    # Session 3 -> July 8 close, after the 10:00 partial: +100 realized, the $200 lot at 174.60 = -25.40.
    three = row["rules"]["exit_session_3"]
    assert three["diff"] == pytest.approx(124.6)
    assert three["cf_pct"] == pytest.approx(74.6 / 500 * 100)


def test_long_hold_without_a_bar_in_three_sessions_or_after_the_actual_exit_keeps_the_actual(tmp_path):
    trade = long_trade(tmp_path)
    row = s.simulate_long(trade, [x.parse_bar(b) for b in LONG_BARS[:2]])  # nothing on July 9, 10 or 13
    assert row["rules"]["exit_session_5"] is None
    early = long_trade(tmp_path, closed="2026-07-07T11:00:00")
    bars = [x.parse_bar(b) for b in LONG_BARS + [daily("2026-07-07", 1.5)]]
    assert s.simulate_long(early, bars)["rules"]["exit_session_3"] is None


def test_long_decisions_follow_the_registered_criteria():
    period = {"touched": 6, "dollar_diff": 10, "pct_diff_mean": 1}
    full = {"touched": 12, "dollar_diff_interval": [5, 50], "dollar_diff_stress": 3}
    both = {"exploration": period, "check": period}
    assert s.decide_long(full, both).startswith("eligible")
    assert s.decide_long(full, {**both, "check": {**period, "touched": 4}}).startswith("investigate")
    assert s.decide_long({**full, "dollar_diff_stress": -1}, both).startswith("reject as")
    assert s.decide_long(full, {**both, "check": {**period, "pct_diff_mean": -1}}).startswith("reject as")
    assert s.decide_long({**full, "dollar_diff_interval": [-5, 50]}, both).startswith("reject as")
    assert s.decide_long({**full, "dollar_diff_interval": [-50, -5]}, both).startswith("reject: exiting")


def test_window_names_from_the_alpaca_cache():
    assert s.window_day("2026-07-02") == date(2026, 7, 2)
    assert s.window_day("2026-07-02T000000-0400") == date(2026, 7, 2)


def test_long_holds_run_end_to_end_from_a_cached_daily_window(tmp_path):
    legs = [(x.ENTRY, "2026-07-02T10:00:00", 2, 300), (x.EXIT, "2026-07-20T14:00:00", 2, 50)]
    long_one = (contract("L", "2026-07-02T10:00:00", "2026-07-20T14:00:00", pnl=-500), fills_for("L", legs))
    unbarred = (contract("U", "2026-07-02T10:00:00", "2026-07-20T14:00:00", pnl=-500, strike=701), fills_for("U", legs))
    short = round_trip("S", "2026-07-02T10:00:00", "2026-07-02T11:00:00", 1, 100, 200)
    path = write_extract(tmp_path, [long_one, unbarred, short])
    folder = tmp_path / "cache" / "options" / "1Day" / "SPY260821C00700000"
    folder.mkdir(parents=True)
    (folder / "2026-07-02_2026-07-21.json").write_text(json.dumps(LONG_BARS))
    results = s.run_long(path, tmp_path / "cache", tmp_path / "out", fetch=False)
    assert results["extract_trades"] == 3 and results["population"] == 2
    assert results["population_actual_total"] == -1000
    assert results["analyzed"] == 1 and results["excluded"] == {"no option daily bars": 1}
    assert results["recorded_pnl_mismatch"] == 0
    one = results["rules"]["exit_session_1"]["all"]
    assert one["touched"] == 1 and one["dollar_diff"] == pytest.approx(385)
    assert one["dollar_diff_interval"] == [pytest.approx(385), pytest.approx(385)]
    assert one["diff_on_losers"] == pytest.approx(385) and one["diff_on_winners"] == 0
    assert "timing_value" not in one
    assert results["rules"]["exit_session_1"]["check"]["touched"] == 1
    assert results["rules"]["exit_session_1"]["decision"].startswith("investigate")  # 0 exploration trades
    assert results["provenance"]["protocol_id"] == s.LONG_ID
    assert (tmp_path / "out" / "long-holds" / "results.json").exists()


def test_protocol_files_name_the_constants_in_code():
    root = Path(__file__).resolve().parents[2] / "research"
    for folder, protocol_id, rules in (("stop-after-green", s.STOP_ID, s.STOP_RULES), ("size-cap", s.CAP_ID, s.CAP_RULES),
                                       ("long-holds", s.LONG_ID, s.LONG_RULES)):
        protocol = json.loads((root / folder / "protocol.json").read_text())
        assert protocol["protocol_id"] == protocol_id
        assert protocol["tests"] == len(rules)
        assert set(rules) <= set(protocol["rules"])
        assert s.REGISTERED_EXTRACT_SHA256 in protocol["population"]["extract"]


def test_fetch_asks_alpaca_for_daily_bars_over_the_trade_window(tmp_path, monkeypatch):
    from app.engine import alpaca

    calls = []

    def fake(symbols, timeframe, start, end):
        calls.append((symbols, timeframe, start, end, alpaca.CACHE_DIR))
        return {symbols[0]: LONG_BARS}

    monkeypatch.setattr(alpaca, "CACHE_DIR", alpaca.CACHE_DIR)
    monkeypatch.setattr(alpaca, "fetch_option_bars", fake)
    legs = [(x.ENTRY, "2026-07-02T10:00:00", 2, 300), (x.EXIT, "2026-07-20T14:00:00", 2, 50)]
    path = write_extract(tmp_path, [(contract("L", "2026-07-02T10:00:00", "2026-07-20T14:00:00", pnl=-500),
                                     fills_for("L", legs))])
    results = s.run_long(path, tmp_path / "cache", tmp_path / "out", fetch=True)
    assert calls == [(["SPY260821C00700000"], "1Day", date(2026, 7, 2), date(2026, 7, 21), tmp_path / "cache")]
    assert results["fetched_windows"] == 1 and results["analyzed"] == 1
